/* global use, db */
// ============================================================
// MongoDB Playground: Create Users Table/Collection in connected Atlas
// ============================================================

// 1. Select the database
use('botdb');

// 2. Create the Users collection with strict schema validation
try {
    db.createCollection('Users', {
        validator: {
            $jsonSchema: {
                bsonType: 'object',
                required: ['name', 'email'],
                properties: {
                    google_id: {
                        bsonType: 'string',
                        description: 'Foreign key reference to Google_Tokens'
                    },
                    name: {
                        bsonType: 'string',
                        maxLength: 150,
                        description: 'name must be a string up to 150 chars and is required'
                    },
                    email: {
                        bsonType: 'string',
                        maxLength: 150,
                        pattern: '^.+@.+\\..+$',
                        description: 'email must be a valid email string and is required'
                    },
                    created_at: {
                        bsonType: 'date',
                        description: 'created_at timestamp'
                    },
                    updated_at: {
                        bsonType: 'date',
                        description: 'updated_at timestamp'
                    }
                }
            }
        }
    });
    console.log('Collection Users created with validation rules.');
} catch (e) {
    console.log('Collection Users status:', e.message);
}

// 3. Create Indexes
// Unique index on email (enforces UNIQUE constraint)
db.getCollection('Users').createIndex({ email: 1 }, { unique: true });

// Index on google_id for fast foreign key lookups
db.getCollection('Users').createIndex({ google_id: 1 });

// // 4. Insert sample user linked to Google_Tokens to verify
// const sampleToken = db.getCollection('Google_Tokens').findOne();
// const sampleGoogleId = sampleToken
//     ? (sampleToken.google_id ? String(sampleToken.google_id) : sampleToken._id.toString())
//     : '1001';

// try {
//     db.getCollection('Users').insertOne({
//         user_id: 1,
//         google_id: sampleGoogleId,
//         name: 'Sample User',
//         email: 'user@example.com',
//         created_at: new Date(),
//         updated_at: new Date()
//     });
//     console.log('Sample user record created.');
// } catch (e) {
//     console.log('Sample user record status:', e.message);
// }

// 5. Display collections and query Users
console.log('Active collections in botdb:', db.getCollectionNames());
db.getCollection('Users').find();
