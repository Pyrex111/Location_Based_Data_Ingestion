"""Exercise upload routes with mocked OpenCage and S3, without cloud writes."""

import io
import unittest
from unittest.mock import Mock, patch

import requests
from botocore.exceptions import ClientError, NoCredentialsError

from app import app


class UploadTests(unittest.TestCase):
    def setUp(self):
        self.saved_config = {
            name: app.config[name]
            for name in ("S3_BUCKET", "OPENCAGE_API_KEY", "AWS_REGION", "TESTING")
        }
        app.config.update(
            TESTING=True, S3_BUCKET="test-bucket", OPENCAGE_API_KEY="test-geocoding-key"
        )
        self.client = app.test_client()
        self.s3 = Mock()
        self.s3_patch = patch("app.get_s3_client", return_value=self.s3)
        self.get_patch = patch("app.requests.get")
        self.s3_factory = self.s3_patch.start()
        self.http_get = self.get_patch.start()
        self.response = Mock()
        self.response.json.return_value = {"results": [{"components": {"city": "Saanich"}}]}
        self.http_get.return_value = self.response

    def tearDown(self):
        self.s3_patch.stop()
        self.get_patch.stop()
        app.config.update(self.saved_config)

    def upload(self, **fields):
        return self.client.post(
            "/upload",
            data={"files[]": (io.BytesIO(b"sample content"), "sample.txt"), **fields},
            content_type="multipart/form-data",
        )

    def test_portal_and_javascript_are_served(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"/static/upload.js", response.data)
        self.assertIn(b"Taimoor, Suhan, Guangning, Lucy", response.data)
        with self.client.get("/static/upload.js") as javascript:
            self.assertEqual(javascript.status_code, 200)

    def test_coordinates_upload_file_bytes_under_city_prefix(self):
        self.s3.upload_fileobj.side_effect = lambda stream, bucket, key: self.assertEqual(
            stream.read(), b"sample content"
        )
        response = self.upload(latitude="48.45", longitude="-123.38")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["uploaded"], ["Saanich/sample.txt"])
        self.assertEqual(self.s3.upload_fileobj.call_args.args[1:], ("test-bucket", "Saanich/sample.txt"))
        self.assertEqual(self.http_get.call_args.kwargs["timeout"], 10)
        self.assertEqual(self.http_get.call_args.kwargs["params"]["q"], "48.45,-123.38")

    def test_manual_city_bypasses_geocoding_without_coordinates(self):
        response = self.upload(manual_city="Victoria")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["uploaded"], ["Victoria/sample.txt"])
        self.http_get.assert_not_called()

    def test_missing_coordinates_prompt_manual_fallback_without_network(self):
        response = self.upload()
        self.assertEqual(response.status_code, 400)
        self.assertTrue(response.json["manual_city_required"])
        self.http_get.assert_not_called()
        self.s3_factory.assert_not_called()

    def test_invalid_coordinates_prompt_manual_fallback(self):
        for latitude, longitude in [("nan", "0"), ("91", "0"), ("0", "181"), ("abc", "0")]:
            with self.subTest(latitude=latitude, longitude=longitude):
                response = self.upload(latitude=latitude, longitude=longitude)
                self.assertEqual(response.status_code, 400)
                self.assertTrue(response.json["manual_city_required"])
        self.http_get.assert_not_called()

    def test_geocoding_timeout_prompts_manual_fallback(self):
        self.http_get.side_effect = requests.Timeout()
        response = self.upload(latitude="48", longitude="-123")
        self.assertEqual(response.status_code, 400)
        self.assertTrue(response.json["manual_city_required"])
        self.s3_factory.assert_not_called()

    def test_geocoding_http_error_prompts_manual_fallback(self):
        self.response.raise_for_status.side_effect = requests.HTTPError()
        response = self.upload(latitude="48", longitude="-123")
        self.assertTrue(response.json["manual_city_required"])

    def test_empty_and_malformed_geocoding_results_prompt_fallback(self):
        for data in [{"results": []}, [], {"results": [{}]}, {"results": "invalid"}]:
            with self.subTest(data=data):
                self.response.json.return_value = data
                response = self.upload(latitude="48", longitude="-123")
                self.assertEqual(response.status_code, 400)
                self.assertTrue(response.json["manual_city_required"])

    def test_missing_opencage_key_still_allows_manual_upload(self):
        app.config["OPENCAGE_API_KEY"] = ""
        response = self.upload(latitude="48", longitude="-123")
        self.assertTrue(response.json["manual_city_required"])
        self.assertEqual(self.upload(manual_city="Toronto").status_code, 200)
        self.http_get.assert_not_called()

    def test_missing_files_rejected_before_services_are_called(self):
        response = self.client.post("/upload", data={"manual_city": "Victoria"})
        self.assertEqual(response.status_code, 400)
        self.http_get.assert_not_called()
        self.s3_factory.assert_not_called()

    def test_city_and_filename_are_normalized_for_s3(self):
        response = self.client.post(
            "/upload",
            data={"manual_city": "Salt Spring Island", "files[]": (io.BytesIO(b"a"), "../report.txt")},
        )
        self.assertEqual(response.json["uploaded"], ["Salt_Spring_Island/report.txt"])

    def test_missing_bucket_is_reported_without_cloud_access(self):
        app.config["S3_BUCKET"] = ""
        response = self.upload(manual_city="Victoria")
        self.assertEqual(response.status_code, 503)
        self.s3_factory.assert_not_called()

    def test_missing_aws_credentials_return_json_error(self):
        self.s3_factory.side_effect = NoCredentialsError()
        response = self.upload(manual_city="Victoria")
        self.assertEqual(response.status_code, 500)
        self.assertIn("credentials", response.json["message"])

    def test_s3_permission_error_returns_json_error(self):
        self.s3.upload_fileobj.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "Denied"}}, "PutObject"
        )
        response = self.upload(manual_city="Victoria")
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json["uploaded"], [])

    def test_multiple_files_uploaded_under_one_city(self):
        response = self.client.post(
            "/upload",
            data={"manual_city": "Victoria", "files[]": [(io.BytesIO(b"a"), "a.txt"), (io.BytesIO(b"b"), "b.txt")]},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["uploaded"], ["Victoria/a.txt", "Victoria/b.txt"])
        self.assertEqual(self.s3.upload_fileobj.call_count, 2)


if __name__ == "__main__":
    unittest.main()
