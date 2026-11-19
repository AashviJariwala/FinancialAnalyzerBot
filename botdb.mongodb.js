/* global use, db */
// MongoDB Playground
// To disable this template go to Settings | MongoDB | Use Default Template For Playground.
// Make sure you are connected to enable completions and to be able to run a playground.
// Use Ctrl+Space inside a snippet or a string literal to trigger completions.
// The result of the last command run in a playground is shown on the results panel.
// By default the first 20 documents will be returned with a cursor.
// Use 'console.log()' to print to the debug output.
// For more documentation on playgrounds please refer to
// https://www.mongodb.com/docs/mongodb-vscode/playgrounds/

// Select the database to use.
use('botdb');

// Insert a few documents into the sales collection.
db.getCollection('test').insertMany([
    { 'item': 'abc', 'price': 10, 'quantity': 2, 'date': new Date('2014-03-01T08:00:00Z') },
    { 'item': 'jkl', 'price': 20, 'quantity': 1, 'date': new Date('2014-03-01T09:00:00Z') },
    { 'item': 'xyz', 'price': 5, 'quantity': 10, 'date': new Date('2014-03-15T09:00:00Z') },
    { 'item': 'xyz', 'price': 5, 'quantity': 20, 'date': new Date('2014-04-04T11:21:39.736Z') },
    { 'item': 'abc', 'price': 10, 'quantity': 10, 'date': new Date('2014-04-04T21:23:13.331Z') },
    { 'item': 'def', 'price': 7.5, 'quantity': 5, 'date': new Date('2015-06-04T05:08:13Z') },
    { 'item': 'def', 'price': 7.5, 'quantity': 10, 'date': new Date('2015-09-10T08:43:00Z') },
    { 'item': 'abc', 'price': 10, 'quantity': 5, 'date': new Date('2016-02-06T20:20:13Z') },
]);

// Run a find command to view items sold on April 4th, 2014.
const salesOnApril4th = db.getCollection('test').find({
    date: { $gte: new Date('2014-04-04'), $lt: new Date('2014-04-05') }
}).count();

// Print a message to the output window.
console.log(`${salesOnApril4th} sales occurred in 2014.`);

// Here we run an aggregation and open a cursor to the results.
// Use '.toArray()' to exhaust the cursor to return the whole result set.
// You can use '.hasNext()/.next()' to iterate through the cursor page by page.
db.getCollection('test').aggregate([
    // Find all of the sales that occurred in 2014.
    { $match: { date: { $gte: new Date('2014-01-01'), $lt: new Date('2015-01-01') } } },
    // Group the total sales for each product.
    { $group: { _id: '$item', totalSaleAmount: { $sum: { $multiply: ['$price', '$quantity'] } } } }
]);

// ============================================================
// CREATE GOOGLE_TOKENS COLLECTION IN CONNECTED ATLAS
// ============================================================

try {
    db.createCollection('Google_Tokens', {
        validator: {
            $jsonSchema: {
                bsonType: 'object',
                required: ['google_id', 'access_token', 'refresh_token', 'expiry_time'],
                properties: {
                    google_id: {
                        bsonType: ['int', 'long', 'number'],
                        description: 'must be an integer and is required'
                    },
                    access_token: {
                        bsonType: 'string',
                        description: 'must be text and is required'
                    },
                    refresh_token: {
                        bsonType: 'string',
                        description: 'must be text and is required'
                    },
                    expiry_time: {
                        bsonType: 'date',
                        description: 'must be a datetime and is required'
                    }
                }
            }
        }
    });
    console.log('Created Google_Tokens collection successfully.');
} catch (e) {
    console.log('Google_Tokens status:', e.message);
}

// Index on google_id
db.getCollection('Google_Tokens').createIndex({ google_id: 1 }, { unique: true });

// Insert a sample token record to verify
db.getCollection('Google_Tokens').insertOne({
    google_id: 101,
    access_token: 'sample_access_token_123',
    refresh_token: 'sample_refresh_token_456',
    expiry_time: new Date(Date.now() + 3600 * 1000)
});

// View all collections and tokens
console.log('Collections in database:', db.getCollectionNames());
db.getCollection('Google_Tokens').find();

