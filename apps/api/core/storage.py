from storages.backends.s3 import S3Storage


class PrivateS3Storage(S3Storage):
    default_acl = "private"
    file_overwrite = False
    querystring_auth = True
