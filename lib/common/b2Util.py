import os
import json
import base64
import hashlib
import requests
from logConfig import get_logger

logger = get_logger(__name__)


class B2Util(object):

    DEFAULT_B2_AUTH_ACCOUNT_REST_API = 'https://api.backblazeb2.com/b2api/v1/b2_authorize_account'

    def __init__(self, upload_config):
        self.upload_config = upload_config

        # get b2 auth token
        self.auth_token, self.api_url, self.download_url = self.get_auth_token()

        if self.auth_token and self.api_url and self.download_url:
            self.auth_sucess = True
            logger.debug("B2 is successfully authenticate, the current auth_toke:[%s], api_url:[%s], download_url:[%s]" % (self.auth_token, self.api_url, self.download_url))
        else:
            self.auth_sucess = False
            logger.error("B2 happends some error during authenication, the current auth_toke:[%s], api_url:[%s], download_url:[%s]" % (self.auth_token, self.api_url, self.download_url))

    def get_upload_url(self, input_bucket_id):
        """
        Use bucket id and auth token to get the upload url
        @param input_bucket_id:
        @return: upload url
        """
        if self.auth_sucess:
            DEFAULT_GET_UPLOAD_URL = self.api_url + "/b2api/v1/b2_get_upload_url"
            url_data = json.dumps({'bucketId': input_bucket_id})
            url_header = {'Authorization': self.auth_token}
            response_data = self.request_and_response(DEFAULT_GET_UPLOAD_URL, url_data, url_header)
            if response_data:
                logger.debug("B2 get new upload url: %s" % response_data['uploadUrl'])
                return response_data['authorizationToken'], response_data['uploadUrl']
            else:
                return None, None
        else:
            logger.error("B2 authenticiation failed, please check the authenication error message above!")
            return None, None

    def get_bucket_list(self):
        """
        get bucket list via account id
        @return:
        """
        if self.auth_sucess:
            DEFAULT_GET_BUCKET_LIST_URL = self.api_url + '/b2api/v1/b2_list_buckets'
            url_data = json.dumps({'accountId': self.acct_id})
            url_header = {'Authorization': self.auth_token}
            response_data = self.request_and_response(DEFAULT_GET_BUCKET_LIST_URL, url_data, url_header)
            if response_data:
                logger.debug("Get bucket list success, buckets data: [%s]" % response_data['buckets'])
                return response_data['buckets']
            else:
                return None
        else:
            logger.error("B2 authenticiation failed, please check the authenication error message above!")
            return None

    def upload_file(self, input_file_path, input_upload_dir_name=None, input_content_type="video/x-matroska"):
        """
        Use bucket id and file path to upload file
        @param input_bucket_id: pre-created bucket id
        @param input_file_path: upload file path
        @param input_content_type:
        @return: file id
        """
        if self.auth_sucess:
            # will based on your bucket name to check if the bucket exist. If not exist, will create new bucket for it
            bucket_name = self.upload_config.get("b2-upload-video-bucket-name", None)
            if bucket_name:
                bucket_list = self.get_bucket_list()
                for bucket_obj in bucket_list:
                    if bucket_obj['bucketName'] == bucket_name:
                        bucket_id = bucket_obj['bucketId']
                        break
                if not bucket_id:
                    bucket_id = self.create_bucket(bucket_name)
            else:
                logger.error("Please specify bucket name in your upload config!!!")
                return None

            # if bucket id is assigned in upload config, will use that bucket id to get upload url
            self.auth_token, upload_url = self.get_upload_url(bucket_id)

            if os.path.exists(input_file_path):
                with open(input_file_path, 'rb') as fh:
                    file_data = fh.read()
                    file_name = os.path.basename(input_file_path)
                    sha1_of_file_data = hashlib.sha1(file_data).hexdigest()
                    if input_upload_dir_name:
                        upload_file_name = input_upload_dir_name + "/" + file_name
                    else:
                        upload_file_name = file_name
            else:
                logger.error("The file[%s] you specify for uploading is not exist!" % input_file_path)
                return None

            headers = {
                'Authorization': self.auth_token,
                'Content-Length': str(os.path.getsize(input_file_path)),
                'X-Bz-File-Name': upload_file_name,
                'Content-Type': input_content_type,
                'X-Bz-Content-Sha1': sha1_of_file_data
            }
            response_data = self.request_and_response(upload_url, file_data, headers)

            if response_data:
                download_url = "%s/file/%s/%s" % (self.download_url, bucket_name, upload_file_name)
                logger.debug("B2 upload file success, the download url : [%s]" % download_url)
                return download_url
            else:
                return None
        else:
            logger.error("B2 authenticiation failed, please check the authenication error message above!")
            return None

    def request_and_response(self, input_url, input_data, input_headers):
        response = requests.post(input_url, data=input_data, headers=input_headers)
        if response.status_code == 200:
            return response.json()
        else:
            logger.error("Send request to url:[%s], with data:[%s] and header:[%s] failed, error code:[%s]" % (input_url, input_data, input_headers, response.status_code))
            return None

    def create_bucket(self, input_bucket_name, input_bucket_type="allPublic", input_bucket_lifecyclerules=None):
        """
        After auth successfully, you can call use this function to create new bucket
        @param input_bucket_name: the bucket name
        @param input_bucket_type: the bucket type, allPublic/allPrivate
        @param input_bucket_lifecyclerules: ref: https://www.backblaze.com/b2/docs/lifecycle_rules.html
        @return: bucket ID
        """
        if self.auth_sucess:
            DEFAULT_CREATE_BUCKET_URL = self.api_url + "/b2api/v1/b2_create_bucket"
            params = {'accountId': self.acct_id, 'bucketName': input_bucket_name,
                      'bucketType': input_bucket_type}
            if input_bucket_lifecyclerules:
                params['lifecycleRules'] = input_bucket_lifecyclerules
            url_data = json.dumps(params)
            url_header = {'Authorization': self.auth_token}
            response_data = self.request_and_response(DEFAULT_CREATE_BUCKET_URL, url_data, url_header)
            if response_data:
                logger.debug("B2 create new bucket, id: %s" % response_data['bucketId'])
                return response_data['bucketId']
            else:
                return None
        else:
            logger.error("B2 authenticiation failed, please check the authenication error message above!")
            return None

    def get_auth_token(self):
        """
        Use account id and account key to combine the auth string, and send the request to B2 Auth API
        @return: will return the following 3 values
        authorizationToken
        apiUrl
        downloadUrl
        """
        accountId = self.upload_config.get("b2-account-id", None)
        accountKey = self.upload_config.get("b2-account-key", None)
        if accountKey and accountId:
            self.acct_id = accountId
            self.acct_key = accountKey
            idAndKeyString = accountId + ":" + accountKey
            basic_auth_string = "Basic" + base64.b64encode(idAndKeyString)
            url_header = {'Authorization': basic_auth_string}
            url_data = json.dumps({})
            response_data = self.request_and_response(B2Util.DEFAULT_B2_AUTH_ACCOUNT_REST_API, url_data, url_header)
            if response_data:
                return response_data['authorizationToken'], response_data['apiUrl'], response_data['downloadUrl']
            else:
                return None, None, None
        else:
            logger.error("Please specify account_id and account_key in upload config file!")
            return None, None, None
