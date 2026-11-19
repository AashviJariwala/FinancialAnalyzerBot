/* global use, db */
// ============================================================
// MongoDB Playground: Create Google_Tokens in connected MongoDB Atlas
// ============================================================

// 1. Select the database
use('botdb');

// 2. Create the Google_Tokens collection with strict schema validation
try {
    db.createCollection('Google_Tokens', {
        validator: {
            $jsonSchema: {
                bsonType: 'object',
                required: ['google_id', 'access_token', 'refresh_token', 'expiry_time'],
                properties: {
                    google_id: {
                        bsonType: 'string',
                        description: 'google_id is required and must be string'
                    },
                    access_token: {
                        bsonType: 'string',
                        description: 'access_token is required and must be text'
                    },
                    refresh_token: {
                        bsonType: 'string',
                        description: 'refresh_token is required and must be text'
                    },
                    expiry_time: {
                        bsonType: 'date',
                        description: 'expiry_time is required and must be a datetime'
                    }
                }
            }
        }
    });
    console.log('Collection Google_Tokens created with validation rules.');
} catch (e) {
    console.log('Collection Google_Tokens may already exist:', e.message);
}

// 3. Create index on google_id for fast lookups
db.getCollection('Google_Tokens').createIndex({ google_id: 1 }, { unique: true });


// 5. Display collections and verify the newly created document
console.log('Active collections in botdb:', db.getCollectionNames());
db.getCollection('Google_Tokens').find();
