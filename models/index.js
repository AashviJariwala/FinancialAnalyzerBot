const {
    createMongooseModel,
    mongoCollectionValidator,
    createGoogleTokensCollection,
} = require('./googleTokens');

const {
    createMongooseUserModel,
    userCollectionValidator,
    createUsersCollection,
} = require('./user');

// Helper to initialize all models at once with mongoose instance
const initModels = (mongoose) => {
    return {
        GoogleToken: createMongooseModel(mongoose),
        User: createMongooseUserModel(mongoose),
    };
};

module.exports = {
    initModels,

    // Google Tokens
    createMongooseModel,
    mongoCollectionValidator,
    createGoogleTokensCollection,

    // Users
    createMongooseUserModel,
    userCollectionValidator,
    createUsersCollection,
};
