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


def configure_splat(
    function_region: str = "ap-southeast-2",
    function_name: str = "splat-prod",
    default_bucket_name: str = "",
    default_tagging: str = "ExpireAfter=1w",
    get_session_fn: Callable[[], Any] = get_session,
    delete_key_fn: Callable[[str, str], None] = delete_key,
):
    """Configure the splat function.

    :param function_region: the default region for the splat function
    :param function_name: the name of the splat function
    :param default_bucket_name: the default bucket name to store html uploaded to s3
    :param default_tagging: the default tag to apply to html uploaded to s3
    :param get_session_fn: a function that returns a boto3 session
    :param default_key_delete_fn: a function that deletes a key from s3
    """
    global config
    config = Config(
        function_region=function_region,
        function_name=function_name,
        default_bucket_name=default_bucket_name,
        default_tagging=default_tagging,
        get_session_fn=get_session_fn,
        delete_key_fn=delete_key_fn,
    )


@dataclass
class Config:
    function_region: str
    function_name: str
    default_bucket_name: str
    default_tagging: str

    get_session_fn: Callable[[], Any]
    delete_key_fn: Callable[[str, str], None]


configure_splat()
