#
# Copyright (c) 2023 Airbyte, Inc., all rights reserved.
#

import logging
from contextlib import contextmanager
from functools import lru_cache
from io import IOBase
from typing import Iterable, List, Optional

import smart_open
from airbyte_cdk.sources.file_based.file_based_stream_reader import AbstractFileBasedStreamReader, FileReadMode
from airbyte_cdk.sources.file_based.remote_file import RemoteFile
from msal import ConfidentialClientApplication
from msal.exceptions import MsalServiceError
from office365.graph_client import GraphClient
from source_microsoft_onedrive.spec import SourceMicrosoftOneDriveSpec


class MicrosoftOneDriveRemoteFile(RemoteFile):
    download_url: str


class MicrosoftOneDriveClient:
    """
    Client to interact with Microsoft OneDrive.
    """

    def __init__(self, config: SourceMicrosoftOneDriveSpec):
        self.config = config
        self._client = None

    @property
    @lru_cache(maxsize=None)
    def msal_app(self):
        """Returns an MSAL app instance for authentication."""
        return ConfidentialClientApplication(
            self.config.credentials.client_id,
            authority=f"https://login.microsoftonline.com/{self.config.credentials.tenant_id}",
            client_credential=self.config.credentials.client_secret,
        )

    @property
    def client(self):
        """Initializes and returns a GraphClient instance."""
        if not self.config:
            raise ValueError("Configuration is missing; cannot create the Office365 graph client.")
        if not self._client:
            self._client = GraphClient(self._get_access_token)
        return self._client

    def _get_access_token(self):
        """Retrieves an access token for OneDrive access."""
        scope = ["https://graph.microsoft.com/.default"]
        refresh_token = self.config.credentials.refresh_token

        result = None
        if refresh_token:
            result = self.msal_app.acquire_token_by_refresh_token(refresh_token, scopes=scope)
        else:
            result = self.msal_app.acquire_token_for_client(scopes=scope)

        if "access_token" not in result:
            error_description = result.get("error_description", "No error description provided.")
            raise MsalServiceError(error=result.get("error"), error_description=error_description)

        return result


class SourceMicrosoftOneDriveStreamReader(AbstractFileBasedStreamReader):
    """
    A stream reader for Microsoft OneDrive. Handles file enumeration and reading from OneDrive.
    """

    def __init__(self):
        super().__init__()

    @property
    def config(self) -> SourceMicrosoftOneDriveSpec:
        return self._config

    @property
    def one_drive_client(self) -> SourceMicrosoftOneDriveSpec:
        return MicrosoftOneDriveClient(self._config).client

    @config.setter
    def config(self, value: SourceMicrosoftOneDriveSpec):
        """
        The FileBasedSource reads and parses configuration from a file, then sets this configuration in its StreamReader. While it only
        uses keys from its abstract configuration, concrete StreamReader implementations may need additional keys for third-party
        authentication. Therefore, subclasses of AbstractFileBasedStreamReader should verify that the value in their config setter
        matches the expected config type for their StreamReader.
        """
        assert isinstance(value, SourceMicrosoftOneDriveSpec)
        self._config = value

    def list_directories_and_files(self, root_folder):
        """Enumerates folders and files starting from a root folder."""
        drive_items = root_folder.children.get().execute_query()
        found_items = []
        for item in drive_items:
            if item.is_file:
                found_items.append(item)
            else:
                found_items.extend(self.list_directories_and_files(item))
        return found_items

    def get_files(self, drives):
        """Yields files from the specified drives."""
        for drive in drives:
            yield from self.list_directories_and_files(drive.root)

    def get_matching_files(self, globs: List[str], prefix: Optional[str], logger: logging.Logger) -> Iterable[RemoteFile]:
        """
        Retrieve all files matching the specified glob patterns in OneDrive.
        """
        my_drive = self.one_drive_client.me.drive.get().execute_query()
        drives = self.one_drive_client.drives.get().execute_query()
        drives.add_child(my_drive)

        files = self.get_files(drives)
        yield from self.filter_files_by_globs_and_start_date([
            MicrosoftOneDriveRemoteFile(uri=file.name, download_url=file.properties["@microsoft.graph.downloadUrl"],
                                        last_modified=file.properties["lastModifiedDateTime"].strftime("%Y-%m-%dT%H:%M:%S.%fZ"))
            for file in files
        ], globs)

    @contextmanager
    def open_file(self, file: RemoteFile, mode: FileReadMode, encoding: Optional[str], logger: logging.Logger) -> IOBase:
        """
        Context manager to open and yield a remote file from OneDrive for reading.
        """
        try:
            with smart_open.open(file.download_url, mode=mode.value, encoding=encoding) as file_handle:
                yield file_handle
        except Exception as e:
            logger.exception(f"Error opening file {file.uri}: {e}")
