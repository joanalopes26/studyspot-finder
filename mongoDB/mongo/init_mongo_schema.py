"""
Cria a base de dados, as coleções com as regras de validação JSON Schema
e o índice geoespacial 2dsphere.
"""

import sys
from pymongo import MongoClient

MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "studyspot"

def main():
    print("A ligar ao MongoDB em", MONGO_URI, "...")
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    try:
        client.admin.command("ping")
        print("Ligação ao MongoDB estabelecida com sucesso.")
    except Exception as e:
        print(f"ERRO: Não foi possível ligar ao MongoDB ({e}).")
        print("Verifica se o serviço mongod está em execução.")
        sys.exit(1)

    db = client[DB_NAME]

    # Dropar coleções existentes
    print("A limpar coleções antigas...")
    db.venues.drop()
    db.reviews.drop()
    db.users.drop()

    # 1. Coleção Venues
    print("A criar coleção 'venues' com validação JSON Schema...")
    venues_validator = {
        "$jsonSchema": {
            "bsonType": "object",
            "required": ["_id", "name", "city", "state", "location", "stars", "review_count", "is_open", "categories"],
            "properties": {
                "_id": {"bsonType": "string"},
                "name": {"bsonType": "string", "minLength": 1},
                "city": {"bsonType": "string"},
                "state": {"bsonType": "string"},
                "stars": {"bsonType": ["double", "int"], "minimum": 1, "maximum": 5},
                "review_count": {"bsonType": ["int", "long"], "minimum": 0},
                "is_open": {"bsonType": "bool"},
                "categories": {
                    "bsonType": "array",
                    "minItems": 1,
                    "items": {"bsonType": "string"}
                },
                "location": {
                    "bsonType": "object",
                    "required": ["type", "coordinates"],
                    "properties": {
                        "type": {"enum": ["Point"]},
                        "coordinates": {
                            "bsonType": "array",
                            "minItems": 2,
                            "maxItems": 2,
                            "items": {"bsonType": "double", "minimum": -180, "maximum": 180}
                        }
                    }
                },
                "amenities": {
                    "bsonType": "object",
                    "properties": {
                        "wifi": {"enum": ["free", "paid", "no"]},
                        "noise_level": {"enum": ["quiet", "average", "loud", "very_loud"]},
                        "outlet_mentions": {"bsonType": ["int", "long"], "minimum": 0}
                    }
                },
                "recent_reviews": {
                    "bsonType": "array",
                    "maxItems": 10,
                    "items": {
                        "bsonType": "object",
                        "required": ["review_id", "user_id", "stars", "date"],
                        "properties": {
                            "stars": {"bsonType": "int", "minimum": 1, "maximum": 5},
                            "date": {"bsonType": "date"},
                            "text_snippet": {"bsonType": "string", "maxLength": 200}
                        }
                    }
                }
            }
        }
    }
    db.create_collection("venues", validator=venues_validator, validationLevel="strict", validationAction="error")

    # 2. Coleção Reviews
    print("A criar coleção 'reviews' com validação JSON Schema...")
    reviews_validator = {
        "$jsonSchema": {
            "bsonType": "object",
            "required": ["_id", "venue_id", "user_id", "stars", "date", "text"],
            "properties": {
                "_id": {"bsonType": "string"},
                "venue_id": {"bsonType": "string"},
                "user_id": {"bsonType": "string"},
                "stars": {"bsonType": "int", "minimum": 1, "maximum": 5},
                "useful": {"bsonType": ["int", "long"], "minimum": 0},
                "funny": {"bsonType": ["int", "long"], "minimum": 0},
                "cool": {"bsonType": ["int", "long"], "minimum": 0},
                "date": {"bsonType": "date"},
                "text": {"bsonType": "string"},
                "mentions_wifi": {"bsonType": "bool"},
                "mentions_outlets": {"bsonType": "bool"},
                "mentions_pastry": {"bsonType": "bool"}
            }
        }
    }
    db.create_collection("reviews", validator=reviews_validator, validationLevel="strict", validationAction="error")

    # 3. Coleção Users
    print("A criar coleção 'users' com validação JSON Schema...")
    users_validator = {
        "$jsonSchema": {
            "bsonType": "object",
            "required": ["_id", "name", "review_count", "yelping_since"],
            "properties": {
                "_id": {"bsonType": "string"},
                "name": {"bsonType": "string"},
                "review_count": {"bsonType": ["int", "long"], "minimum": 0},
                "yelping_since": {"bsonType": "date"},
                "average_stars": {"bsonType": ["double", "int"], "minimum": 0, "maximum": 5}
            }
        }
    }
    db.create_collection("users", validator=users_validator, validationLevel="strict", validationAction="error")

    # Índice Geoespacial (2dsphere)
    print("A criar índice 2dsphere em 'location'...")
    db.venues.create_index([("location", "2dsphere")])

    print("\n Schema inicializado com sucesso! :D")
    print("Coleções existentes:", db.list_collection_names())
    print("Índices em 'venues':", list(db.venues.list_indexes()))
    client.close()

if __name__ == "__main__":
    main()
