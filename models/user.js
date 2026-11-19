/**
 * User Model for MongoDB Atlas (Node.js)
 *
 * Table / Collection: Users
 * Columns:
 *  - google_id: VARCHAR(255) (FK -> Google_tokens(google_id))
 *  - name: VARCHAR(150), NOT NULL
 *  - email: VARCHAR(150), UNIQUE, NOT NULL
 *  - created_at: TIMESTAMP, DEFAULT CURRENT_TIMESTAMP
 *  - updated_at: TIMESTAMP, ON UPDATE CURRENT_TIMESTAMP
 */

// 1. Mongoose Model (for Node.js Mongoose ODM)
const createMongooseUserModel = (mongoose) => {
    const userSchema = new mongoose.Schema(
        {
            google_id: {
                type: String,
                maxlength: 255,
                ref: 'GoogleToken',
                default: null,
            },
            name: {
                type: String,
                required: [true, 'Name is required'],
                maxlength: [150, 'Name cannot exceed 150 characters'],
                trim: true,
            },
            email: {
                type: String,
                required: [true, 'Email is required'],
                unique: true,
                maxlength: [150, 'Email cannot exceed 150 characters'],
                lowercase: true,
                trim: true,
                match: [/.+@.+\..+/, 'Please provide a valid email address'],
            },
        },
        {
            collection: 'Users',
            timestamps: {
                createdAt: 'created_at',
                updatedAt: 'updated_at',
            },
        }
    );

    return mongoose.models.User || mongoose.model('User', userSchema);
};

// 2. Native MongoDB Schema Validator
const userCollectionValidator = {
    validator: {
        $jsonSchema: {
            bsonType: 'object',
            required: ['name', 'email'],
            properties: {
                google_id: {
                    bsonType: 'string',
                    description: 'Foreign key referencing Google_tokens',
                },
                name: {
                    bsonType: 'string',
                    maxLength: 150,
                    description: 'name must be a string up to 150 characters and is required',
                },
                email: {
                    bsonType: 'string',
                    maxLength: 150,
                    description: 'email must be unique and is required',
                },
                created_at: {
                    bsonType: 'date',
                    description: 'timestamp when document was created',
                },
                updated_at: {
                    bsonType: 'date',
                    description: 'timestamp when document was last updated',
                },
            },
        },
    },
};

// 3. Helper to create collection using native MongoDB Node driver
async function createUsersCollection(db) {
    const collections = await db.listCollections({ name: 'Users' }).toArray();
    if (collections.length === 0) {
        await db.createCollection('Users', userCollectionValidator);
        await db.collection('Users').createIndex({ email: 1 }, { unique: true });
        await db.collection('Users').createIndex({ google_id: 1 });
        console.log("Collection 'Users' created successfully in MongoDB Atlas.");
    } else {
        console.log("Collection 'Users' already exists in MongoDB Atlas.");
    }
}

module.exports = {
    createMongooseUserModel,
    userCollectionValidator,
    createUsersCollection,
};
