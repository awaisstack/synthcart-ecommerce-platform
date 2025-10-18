"""
Bronze Layer - API Data Ingestion
Author: Afnan Khan
Description: Fetches product and user data from DummyJSON API and uploads to MinIO bronze bucket
"""

import requests
import json
from minio import Minio
from minio.error import S3Error
from datetime import datetime
import logging
import io

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class APIDataIngestion:
    def __init__(self):
        # MinIO configuration
        self.minio_client = Minio(
            "minio:9000",
            access_key="minioadmin",
            secret_key="minioadmin",
            secure=False
        )
        self.bucket_name = "bronze"
        
        # API endpoints
        self.api_endpoints = {
            "products": "https://dummyjson.com/products",
            "users": "https://dummyjson.com/users"
        }
    
    def setup_minio_bucket(self):
        """Create bronze bucket if it doesn't exist"""
        try:
            if not self.minio_client.bucket_exists(self.bucket_name):
                self.minio_client.make_bucket(self.bucket_name)
                logger.info(f"Created bucket: {self.bucket_name}")
            else:
                logger.info(f"Bucket {self.bucket_name} already exists")
        except S3Error as e:
            logger.error(f"Error creating bucket: {e}")
            raise
    
    def fetch_api_data(self, endpoint_name, url):
        """Fetch data from API endpoint"""
        try:
            logger.info(f"Fetching data from {endpoint_name}: {url}")
            
            response = requests.get(url)
            response.raise_for_status()  # Raise an exception for bad status codes
            
            data = response.json()
            logger.info(f"Successfully fetched {endpoint_name} data")
            
            return data
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching data from {endpoint_name}: {e}")
            raise
        except json.JSONDecodeError as e:
            logger.error(f"Error parsing JSON from {endpoint_name}: {e}")
            raise
    
    def upload_json_to_minio(self, data, endpoint_name):
        """Upload JSON data to MinIO bronze bucket"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            object_name = f"api_data/{timestamp}/{endpoint_name}.json"
            
            # Convert data to JSON string and then to bytes
            json_data = json.dumps(data, indent=2)
            json_bytes = json_data.encode('utf-8')
            
            # Create a BytesIO object
            json_buffer = io.BytesIO(json_bytes)
            
            # Upload to MinIO
            self.minio_client.put_object(
                self.bucket_name,
                object_name,
                json_buffer,
                length=len(json_bytes),
                content_type='application/json'
            )
            
            logger.info(f"Uploaded {endpoint_name} data to {object_name}")
            
        except Exception as e:
            logger.error(f"Error uploading {endpoint_name} data to MinIO: {e}")
            raise
    
    def run_ingestion(self):
        """Main method to run the complete API ingestion process"""
        try:
            logger.info("Starting API data ingestion process")
            
            # Setup MinIO bucket
            self.setup_minio_bucket()
            
            # Fetch and upload data from each API endpoint
            for endpoint_name, url in self.api_endpoints.items():
                # Fetch data from API
                api_data = self.fetch_api_data(endpoint_name, url)
                
                # Upload to MinIO
                self.upload_json_to_minio(api_data, endpoint_name)
            
            logger.info("API data ingestion completed successfully")
            
        except Exception as e:
            logger.error(f"API ingestion process failed: {e}")
            raise

if __name__ == "__main__":
    ingestion = APIDataIngestion()
    ingestion.run_ingestion()