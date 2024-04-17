from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import boto3

from .logging import logger


def get_session() -> Any:
    """This function can be overridden to provide a custom session"""
    session = boto3.session.Session()
    return session


def get_tmp_html_key() -> str:
    """This function can be overridden to provide a custom storage_location for temporary html files"""
    return f"tmp/{uuid4()}.html"


def delete_key(bucket_name: str, path: str) -> None:
    """This function can be overriden to provide a custom delete key function"""
    global config
    session = config.get_session_fn()
    s3_client = session.client("s3")
    try:
        s3_client.delete_object(Bucket=bucket_name, Key=path)
    except Exception as e: # noqa
        logger.warning(f"Failed to delete {path} from s3: {e}")


def configure_splat(
    function_region: str | None = None,
    function_name: str | None = None,
    default_bucket_name: str | None = None,
    default_tagging: str | None = None,
    get_session_fn: Callable[[], Any] | None = None,
    get_tmp_html_key_fn: Callable[[str], str] | None = None,
    delete_key_fn: Callable[[str, str], None] | None = None,
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
    if function_region is not None:
        config.function_region = function_region
    if function_name is not None:
        config.function_name = function_name
    if default_bucket_name is not None:
        config.default_bucket_name = default_bucket_name
    if default_tagging is not None:
        config.default_tagging = default_tagging
    if get_session_fn is not None:
        config.get_session_fn = get_session_fn
    if get_tmp_html_key_fn is not None:
        config.get_tmp_html_key_fn = get_tmp_html_key_fn
    if delete_key_fn is not None:
        config.delete_key_fn = delete_key_fn


@dataclass
class Config:
    function_region: str
    function_name: str
    default_bucket_name: str
    default_tagging: str

    get_session_fn: Callable[[], Any]
    get_tmp_html_key_fn: Callable[[str], str]
    delete_key_fn: Callable[[str, str], None]


configure_splat()

config = Config(
    function_region="ap-southeast-2",
    function_name="splat-prod",
    default_bucket_name="",
    default_tagging="ExpireAfter=1w",
    get_session_fn=get_session,
    get_tmp_html_key_fn=get_tmp_html_key,
    delete_key_fn=delete_key,
)
