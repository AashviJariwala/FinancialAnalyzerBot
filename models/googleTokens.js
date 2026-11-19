/**
 * Google_Tokens Model for MongoDB Atlas (Node.js)
 *
 * Collection: Google_Tokens
 * Fields:
 *  - google_id: String (required, unique)
 *  - access_token: String (required)
 *  - refresh_token: String (required)
 *  - expiry_time: Date (required)
 */

// 1. Mongoose Schema (for Node.js Mongoose ODM)
const createMongooseModel = (mongoose) => {
    const googleTokenSchema = new mongoose.Schema(
        {
            google_id: {
                type: String,
                required: [true, 'google_id is required'],
                unique: true,
                index: true,
            },
            access_token: {
                type: String,
                required: [true, 'access_token is required'],
            },
            refresh_token: {
                type: String,
                required: [true, 'refresh_token is required'],
            },
            expiry_time: {
                type: Date,
                required: [true, 'expiry_time is required'],
            },
        },
        {
            collection: 'Google_Tokens',
            timestamps: true,
        }
    );

    return mongoose.models.GoogleToken || mongoose.model('GoogleToken', googleTokenSchema);
};

// 2. Native MongoDB Schema Validator
const mongoCollectionValidator = {
    validator: {
        $jsonSchema: {
            bsonType: 'object',
            required: ['google_id', 'access_token', 'refresh_token', 'expiry_time'],
            properties: {
                google_id: {
                    bsonType: 'string',
                    description: 'must be a string and is required',
                },
                access_token: {
                    bsonType: 'string',
                    description: 'must be text and is required',
                },
                refresh_token: {
                    bsonType: 'string',
                    description: 'must be text and is required',
                },
                expiry_time: {
                    bsonType: 'date',
                    description: 'must be a datetime and is required',
                },
            },
        },
    },
};

// 3. Helper to create collection using native MongoDB Node driver
async function createGoogleTokensCollection(db) {
    const collections = await db.listCollections({ name: 'Google_Tokens' }).toArray();
    if (collections.length === 0) {
        await db.createCollection('Google_Tokens', mongoCollectionValidator);
        await db.collection('Google_Tokens').createIndex({ google_id: 1 }, { unique: true });
        console.log("Collection 'Google_Tokens' created in MongoDB Atlas.");
    } else {
        console.log("Collection 'Google_Tokens' already exists in MongoDB Atlas.");
    }
}

module.exports = {
    createMongooseModel,
    mongoCollectionValidator,
    createGoogleTokensCollection,
};
