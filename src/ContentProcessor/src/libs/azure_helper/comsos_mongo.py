"""Cosmos DB (Mongo API) CRUD helper.

Wraps PyMongo operations against an Azure Cosmos DB database exposed
through the MongoDB wire protocol, used by the pipeline to persist
process state and schema data.
"""

import warnings
from typing import Any, Dict

import certifi
from pymongo import MongoClient
from pymongo.database import Collection, Database


class CosmosMongDBHelper:
    """CRUD facade for a single Cosmos DB (Mongo) collection.

    Responsibilities:
        1. Establish a TLS-secured MongoClient connection.
        2. Auto-create the target collection and indexes.
        3. Expose insert / find / update / delete operations.

    Attributes:
        client: The underlying PyMongo MongoClient.
        db: The target database handle.
        container: The target collection handle.
    """

    def __init__(
        self,
        connection_string: str,
        db_name: str,
        container_name: str,
        indexes: list = None,
    ):
        self.connection_string = connection_string
        self.client: MongoClient = None
        self.container: Collection = None
        self.db: Database = None

        self.client, self.db, self.container = self._prepare(
            connection_string, db_name, container_name, indexes
        )

    def _prepare(
        self,
        connection_string: str,
        db_name: str,
        container_name: str,
        indexes: list = None,
    ):
        """Open a Mongo connection, ensure the collection exists, and create indexes.

        Args:
            connection_string: Cosmos DB Mongo connection string.
            db_name: Target database name.
            container_name: Target collection name.
            indexes: Optional field names to index.

        Returns:
            Tuple of (MongoClient, Database, Collection).
        """
        # pymongo emits a noisy CosmosDB compatibility warning; silence it.
        warnings.filterwarnings(
            "ignore",
            message=r"You appear to be connected to a CosmosDB cluster\..*",
            category=UserWarning,
        )
        mongoClient = MongoClient(connection_string, tlsCAFile=certifi.where())
        database = mongoClient[db_name]
        container = self._create_container(database, container_name)
        if indexes:
            self._create_indexes(container, indexes)

        return mongoClient, database, container

    def _create_container(self, database: Database, container_name: str) -> Collection:
        """Ensure the collection exists in the database."""
        if container_name not in database.list_collection_names():
            database.create_collection(container_name)
        return database[container_name]

    def _create_indexes(self, container, fields):
        """Create indexes for *fields* that do not already exist.

        Each entry may be:
            * ``str`` -- ascending single-field index
            * ``(field, order)`` -- 2-tuple, signed order (1 / -1)
            * ``(field, order, unique)`` -- 3-tuple, ``unique`` is a bool
        """
        existing_indexes = container.index_information()
        for entry in fields:
            if isinstance(entry, str):
                field, order, unique = entry, 1, False
            elif len(entry) == 2:
                field, order = entry
                unique = False
            else:
                field, order, unique = entry
            if f"{field}_{order}" not in existing_indexes:
                container.create_index([(field, order)], unique=unique)

    def insert_document(self, document: Dict[str, Any]):
        """Insert a single document and return the insert result."""
        result = self.container.insert_one(document)
        return result

    def find_document(self, query: Dict[str, Any], sort_fields=None):
        """Find documents matching *query*, optionally sorted."""
        if sort_fields:
            items = list(self.container.find(query).sort(sort_fields))
        else:
            items = list(self.container.find(query))
        return items

    def update_document(self, filter: Dict[str, Any], update: Dict[str, Any]):
        """Update a single document matching *filter* with ``$set``."""
        result = self.container.update_one(filter, {"$set": update})
        return result

    def upsert_document_by_query(
        self,
        query: Dict[str, Any],
        set_fields: Dict[str, Any],
        set_on_insert: Dict[str, Any] = None,
    ):
        """Atomic upsert: ``$set`` *set_fields* on match, otherwise insert.

        Eliminates the find-then-write race on Cosmos DB where a concurrent
        worker can flip the document between the read and the subsequent
        insert. ``$setOnInsert`` (when provided) seeds fields that should
        only land on the create path.
        """
        update: Dict[str, Any] = {"$set": set_fields}
        if set_on_insert:
            # PyMongo refuses overlapping keys between $set and $setOnInsert.
            set_on_insert = {
                k: v for k, v in set_on_insert.items() if k not in set_fields
            }
            if set_on_insert:
                update["$setOnInsert"] = set_on_insert
        return self.container.update_one(query, update, upsert=True)

    def delete_document(self, item_id: str):
        """Delete the document whose ``Id`` equals *item_id*."""
        result = self.container.delete_one({"Id": item_id})
        return result
