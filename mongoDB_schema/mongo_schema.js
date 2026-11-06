// mongosh mongo_schema.js   (or paste into mongosh)
// StudySpot Finder - collections, validation rules and the spatial index.
// Extra indexes are intentionally NOT created here: they belong to Goal 4,
// so the baseline measurements are taken with default indexes only.

const dbs = db.getSiblingDB("studyspot");

dbs.venues.drop();
dbs.reviews.drop();
dbs.users.drop();

dbs.createCollection("venues", {
  validator: {
    $jsonSchema: {
      bsonType: "object",
      required: ["_id", "name", "city", "state", "location", "stars",
                 "review_count", "is_open", "categories"],
      properties: {
        _id: { bsonType: "string" },
        name: { bsonType: "string", minLength: 1 },
        city: { bsonType: "string" },
        state: { bsonType: "string" },
        stars: { bsonType: ["double", "int"], minimum: 1, maximum: 5 },
        review_count: { bsonType: ["int", "long"], minimum: 0 },
        is_open: { bsonType: "bool" },
        categories: {
          bsonType: "array", minItems: 1,
          items: { bsonType: "string" }
        },
        location: {
          bsonType: "object",
          required: ["type", "coordinates"],
          properties: {
            type: { enum: ["Point"] },
            coordinates: {
              bsonType: "array", minItems: 2, maxItems: 2,
              items: { bsonType: "double", minimum: -180, maximum: 180 }   // [longitude, latitude]
            }
          }
        },
        amenities: {
          bsonType: "object",
          properties: {
            wifi: { enum: ["free", "paid", "no"] },
            noise_level: { enum: ["quiet", "average", "loud", "very_loud"] },
            outlet_mentions: { bsonType: ["int", "long"], minimum: 0 }
          }
        },
        recent_reviews: {
          bsonType: "array", maxItems: 10,
          items: {
            bsonType: "object",
            required: ["review_id", "user_id", "stars", "date"],
            properties: {
              stars: { bsonType: "int", minimum: 1, maximum: 5 },
              date: { bsonType: "date" },
              text_snippet: { bsonType: "string", maxLength: 200 }
            }
          }
        }
      }
    }
  },
  validationLevel: "strict",
  validationAction: "error"
});

dbs.createCollection("reviews", {
  validator: {
    $jsonSchema: {
      bsonType: "object",
      required: ["_id", "venue_id", "user_id", "stars", "date", "text"],
      properties: {
        _id: { bsonType: "string" },
        venue_id: { bsonType: "string" },
        user_id: { bsonType: "string" },
        stars: { bsonType: "int", minimum: 1, maximum: 5 },
        useful: { bsonType: ["int", "long"], minimum: 0 },
        funny: { bsonType: ["int", "long"], minimum: 0 },
        cool: { bsonType: ["int", "long"], minimum: 0 },
        date: { bsonType: "date" },
        text: { bsonType: "string" },
        mentions_wifi: { bsonType: "bool" },
        mentions_outlets: { bsonType: "bool" },
        mentions_pastry: { bsonType: "bool" }
      }
    }
  },
  validationLevel: "strict",
  validationAction: "error"
});

dbs.createCollection("users", {
  validator: {
    $jsonSchema: {
      bsonType: "object",
      required: ["_id", "name", "review_count", "yelping_since"],
      properties: {
        _id: { bsonType: "string" },
        name: { bsonType: "string" },
        review_count: { bsonType: ["int", "long"], minimum: 0 },
        yelping_since: { bsonType: "date" },
        average_stars: { bsonType: ["double", "int"], minimum: 0, maximum: 5 }
      }
    }
  },
  validationLevel: "strict",
  validationAction: "error"
});

// Spatial index required by $near / $geoNear queries
dbs.venues.createIndex({ location: "2dsphere" });

print("Collections:", dbs.getCollectionNames());
print("Indexes on venues:", JSON.stringify(dbs.venues.getIndexes()));
