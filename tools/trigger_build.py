"""

Usage:
  trigger_build.py [--input-json=<str>]
  trigger_build.py (-h | --help)

Options:
  -h --help                 Show this screen.
  --input-json=<str>        Specify the parsing json for testing
"""
import re
import os
import sys
import json
import copy
import urllib2
import requests

from thclient import TreeherderClient
from docopt import docopt
from tqdm import tqdm


class TriggerBuild(object):
    ARCHIVE_URL = "https://archive.mozilla.org"
    NIGHTLY_LATEST_URL_FOLDER = "/pub/firefox/nightly/latest-mozilla-central/"
    PLATFORM_FN_MAPPING = {'linux32': {'key': 'linux-i686', 'ext': 'tar.bz2', 'trydl': 'linux', 'job': ['linux32']},
                           'linux64': {'key': 'linux-x86_64', 'ext': 'tar.bz2', 'trydl': 'linux64', 'job': ['linux64']},
                           'mac': {'key': 'mac', 'ext': 'dmg', 'trydl': 'macosx64', 'job': ['osx']},
                           'win32': {'key': 'win32', 'ext': 'zip', 'trydl': 'win32', 'job': ['windows', '32']},
                           'win64': {'key': 'win64', 'ext': 'zip', 'trydl': 'win64', 'job': ['windows', '64']}}
    ENV_KEY_TRY_REPO_USER_EMAIL = "EMAIL"
    ENV_KEY_ENABLE_WIN32 = "WIN32_FLAG"
    ENV_KEY_SKIP_STATUS_CHECK = "--SKIP_STATUS_CHECK"
    ENV_KEY_OUTPUT_DP = "OUTPUT_DP"
    ENV_KEY_BUILD_HASH = "BUILD_HASH"
    REPO_NAME = {'TRY': "try", "NIGHTLY": "nightly"}
    HASAL_JSON_FN = "hasal.json"
    DEFAULT_AGENT_CONF_DIR_LINUX = "/home/hasal/Hasal/agent"
    DEFAULT_AGENT_CONF_DIR_MAC = "/Users/hasal/Hasal/agent"
    DEFAULT_AGENT_CONF_DIR_WIN = "C:\\Users\\user\\Hasal\\agent"

    def __init__(self, input_env_data):
        self.platform_option = 'opt'
        self.thclient = TreeherderClient()
        self.resultsets = []
        self.env_data = {key.upper(): value for key, value in input_env_data.items()}
        self.dispatch_variables(self.env_data)

    def dispatch_variables(self, input_env_data):
        # if user email not in environment data, repo will be the nightly
        if self.ENV_KEY_TRY_REPO_USER_EMAIL in input_env_data.keys():
            self.user_email = input_env_data[self.ENV_KEY_TRY_REPO_USER_EMAIL]
            self.repo = self.REPO_NAME['TRY']
        else:
            self.repo = self.REPO_NAME['NIGHTLY']

        # check current platform, widnows will double check the --win32 flag enabled or not
        if sys.platform == "linux2":
            self.platform = "linux64"
        elif sys.platform == "darwin":
            self.platform = "mac"
        else:
            if self.ENV_KEY_ENABLE_WIN32 in input_env_data.keys() and input_env_data[self.ENV_KEY_ENABLE_WIN32] == 'true':
                self.platform = "win32"
            else:
                self.platform = "win64"

        # assign skip status check to variable
        if self.ENV_KEY_SKIP_STATUS_CHECK in input_env_data.keys() and input_env_data[self.ENV_KEY_SKIP_STATUS_CHECK] == 'true':
            self.skip_status_check = True
        else:
            self.skip_status_check = False

        # assign build hash to variable
        if self.ENV_KEY_BUILD_HASH in input_env_data.keys():
            self.build_hash = input_env_data[self.ENV_KEY_BUILD_HASH]
        else:
            self.build_hash = None

        # assign output dp to variable
        if self.ENV_KEY_OUTPUT_DP in input_env_data.keys():
            self.output_dp = input_env_data[self.ENV_KEY_OUTPUT_DP]
        else:
            self.output_dp = os.getcwd()

    def trigger(self):
        # download build
        if self.repo == self.REPO_NAME['TRY']:
            download_fx_fp, download_json_fp = self.get_try_build(self.user_email, self.build_hash, self.output_dp)
        else:
            download_fx_fp, download_json_fp = self.get_nightly_build(self.output_dp)

        # generate hasal.json data
        with open(download_json_fp) as dl_json_fh:
            dl_json_data = json.load(dl_json_fh)
            perfherder_revision = dl_json_data['moz_source_stamp']
            with open(self.HASAL_JSON_FN, "w") as write_fh:
                write_data = copy.deepcopy(self.env_data)
                write_data['FX-DL-PACKAGE-PATH'] = download_fx_fp
                write_data['FX-DL-JSON-PATH'] = download_json_fp
                write_data['--PERFHERDER-REVISION'] = perfherder_revision
                json.dump(write_data, write_fh)

        # move to agent config folder
        if sys.platform == "linux2":
            new_hasal_json_fp = os.path.join(self.DEFAULT_AGENT_CONF_DIR_LINUX, self.HASAL_JSON_FN)
        elif sys.platform == "darwin":
            new_hasal_json_fp = os.path.join(self.DEFAULT_AGENT_CONF_DIR_MAC, self.HASAL_JSON_FN)
        else:
            new_hasal_json_fp = os.path.join(self.DEFAULT_AGENT_CONF_DIR_WIN, self.HASAL_JSON_FN)
        os.rename(self.HASAL_JSON_FN, new_hasal_json_fp)

    def fetch_resultset(self, user_email, build_hash, default_count=500):
        tmp_resultsets = self.thclient.get_resultsets(self.repo, count=default_count)
        for resultset in tmp_resultsets:
            if resultset['author'].lower() == user_email.lower():
                self.resultsets.append(resultset)
                if build_hash is None:
                    return resultset
                elif resultset['revision'] == build_hash:
                    return resultset
        print "Can't find the specify build hash [%s] in resultsets!!" % build_hash
        return None

    def get_job(self, resultset, platform_keyword_list):
        jobs = self.thclient.get_jobs(self.repo, result_set_id=resultset['id'])
        for job in jobs:
            cnt = 0
            for platform_keyword in platform_keyword_list:
                if platform_keyword in job['platform']:
                    cnt += 1
            if job['platform_option'] == self.platform_option and cnt == len(platform_keyword_list):
                return job
        print "Can't find the specify platform [%s] and platform_options [%s] in jobs!!!" % (self.platform, self.platform_option)
        return None

    def get_files_from_remote_url_folder(self, remote_url_str):
        return_dict = {}
        try:
            response_obj = urllib2.urlopen(remote_url_str)
            if response_obj.getcode() == 200:
                for line in response_obj.readlines():
                    match = re.search(r'(?<=href=").*?(?=")', line)
                    if match:
                        href_link = match.group(0)
                        f_name = href_link.split("/")[-1]
                        return_dict[f_name] = href_link
            else:
                print "ERROR: fetch remote file list error with code [%s]" % str(response_obj.getcode())
        except Exception as e:
            print "ERROR: [%s]" % e.message
        return return_dict

    def download_file(self, output_dp, download_link):
        print "Prepare to download the build from link [%s]" % download_link
        response = requests.get(download_link, verify=False, stream=True)
        download_fn = download_link.split("/")[-1]
        if os.path.exists(output_dp) is False:
            os.makedirs(output_dp)
        download_fp = os.path.join(output_dp, download_fn)
        try:
            try:
                total_len = int(response.headers['content-length'])
            except:
                total_len = None
            with open(download_fp, 'wb') as fh:
                for data in tqdm(response.iter_content(), total=total_len):
                    fh.write(data)
            return download_fp
        except Exception as e:
            print "ERROR: [%s]" % e.message
            return None

    def download_from_remote_url_folder(self, remote_url_str, output_dp):
        # get latest nightly build list from remote url folder
        remote_file_dict = self.get_files_from_remote_url_folder(remote_url_str)

        # filter with platform, and return file name with extension
        if len(remote_file_dict.keys()) == 0:
            print "ERROR: can't get remote file list, could be the network error, or url path[%s] wrong!!" % remote_url_str
            return False
        else:
            if self.platform not in self.PLATFORM_FN_MAPPING:
                print "ERROR: we are currently not support the platform[%s] you specified!" % self.platform
                print "We are currently support the platform tag: [%s]" % self.PLATFORM_FN_MAPPING.keys()
                return False
            else:
                matched_keyword = self.PLATFORM_FN_MAPPING[self.platform]['key'] + "." + self.PLATFORM_FN_MAPPING[self.platform]['ext']
                matched_file_list = [fn for fn in remote_file_dict.keys() if matched_keyword in fn and "firefox" in fn]
                if len(matched_file_list) != 1:
                    print "ERROR: the possible match file list is not equal 1, list as below: [%s]" % matched_file_list
                    return False

        # combine file name with json
        matched_file_name = matched_file_list[0]
        json_file_name = matched_file_name.replace(
            self.PLATFORM_FN_MAPPING[self.platform]['key'] + "." + self.PLATFORM_FN_MAPPING[self.platform]['ext'],
            self.PLATFORM_FN_MAPPING[self.platform]['key'] + ".json")
        if json_file_name not in remote_file_dict:
            print "ERROR: can't find the json file[%s] in remote file list[%s]!" % (json_file_name, remote_file_dict)
            return False
        else:
            print "DEBUG: matched file name: [%s], json_file_name: [%s]" % (matched_file_name, json_file_name)

        # download files
        download_fx_url = self.ARCHIVE_URL + remote_file_dict[matched_file_name]
        download_fx_fp = self.download_file(output_dp, download_fx_url)
        download_json_url = self.ARCHIVE_URL + remote_file_dict[json_file_name]
        download_json_fp = self.download_file(output_dp, download_json_url)

        # check download status
        if download_fx_fp and download_json_fp:
            print "SUCCESS: build files download in [%s], [%s] " % (download_fx_fp, download_json_fp)
            return (download_fx_fp, download_json_fp)
        else:
            print "ERROR: build files download in [%s,%s] " % (download_fx_fp, download_json_fp)
            return None

    def get_try_build(self, user_email, build_hash, output_dp):
        resultset = self.fetch_resultset(user_email, build_hash)

        # check result set
        if resultset:
            # if build hash is not porvided, use the latest revision as build hash value
            if build_hash is None:
                build_hash = resultset['revision']
            print "Resultset is found, and build hash is [%s]" % build_hash

            # compose remote folder url
            build_folder_url_template = "%s/pub/firefox/%s-builds/%s-%s/%s-%s/"
            build_folder_url = build_folder_url_template % (self.ARCHIVE_URL,
                                                            self.repo, user_email, build_hash,
                                                            self.repo,
                                                            self.PLATFORM_FN_MAPPING[self.platform][
                                                                'trydl'])

            # skip status check will retrieve the files list from remote folder url
            if self.skip_status_check:
                return self.download_from_remote_url_folder(build_folder_url, output_dp)
            else:
                job = self.get_job(resultset, self.PLATFORM_FN_MAPPING[self.platform]['job'])
                if job:
                    if job['result'].lower() == "success":
                        return self.download_from_remote_url_folder(build_folder_url, output_dp)
                    else:
                        "Current job status is [%s] !!" % job['result'].lower()
                        return False
                else:
                    print "ERROR: can't find the job!"
                    return False
        else:
            print "ERROR: can't get result set! skip download build from try server, [%s, %s]" % (user_email, build_hash)
            return False

    def get_nightly_build(self, output_dp):
        remote_url_str = self.ARCHIVE_URL + self.NIGHTLY_LATEST_URL_FOLDER
        return self.download_from_remote_url_folder(remote_url_str, output_dp)


def main():
    arguments = docopt(__doc__)
    if arguments['--input-json']:
        if os.path.exists(arguments['--input-json']):
            with open(arguments['--input-json']) as fh:
                input_env_data = json.load(fh)
        else:
            print "ERROR: can not find the specify input json file! [%s]" % arguments['--input-json']
            return False
    else:
        input_env_data = os.environ.copy()

    trigger_build_obj = TriggerBuild(input_env_data)
    trigger_build_obj.trigger()

if __name__ == '__main__':
    main()
