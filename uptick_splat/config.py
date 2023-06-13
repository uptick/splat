from dataclasses import dataclass
from typing import Any, Callable

import boto3

from .logging import logger


def get_session() -> Any:
    """This function can be overridden to provide a custom session"""
    session = boto3.session.Session()
    return session


def delete_key(bucket_name: str, path: str) -> None:
    """This function can be overriden to provide a custom delete key function"""
    session = config.get_session()
    s3_client = session.client("s3")
    try:
        s3_client.delete_object(Bucket=bucket_name, Key=path)
    except Exception as e:
        logger.warning(f"Failed to delete {path} from s3: {e}")


@dataclass
class Config:
    function_region: str = "ap-southeast-2"
    function_name: str = "splat-prod"
    default_bucket_name: str = ""
    default_html_key: str = "ExpireAfter=1w"

    get_session: Callable[[], Any] = get_session
    delete_key: Callable[[str, str], None] = delete_key


config = Config()
