from django.conf import settings
from django.core.files.uploadhandler import FileUploadHandler, StopUpload


class BoundedUploadHandler(FileUploadHandler):
    """First handler: cap aggregate file bytes before memory/disk handlers consume them."""

    def __init__(self, request=None):
        super().__init__(request)
        self.received = 0

    def receive_data_chunk(self, raw_data, start):
        self.received += len(raw_data)
        if self.received > getattr(settings, "KAIROS_MAX_UPLOAD_BYTES", 25 * 1024**2):
            self.request.kairos_upload_rejected = True
            raise StopUpload(connection_reset=True)
        return raw_data

    def file_complete(self, file_size):
        return None
