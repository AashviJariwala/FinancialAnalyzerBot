require('dotenv').config();
const express = require('express');
const session = require('express-session');
const mongoose = require('mongoose');
const path = require('path');
const http = require('http');

// Import models from ./models
const { initModels } = require('./models');

const app = express();
const PORT = process.env.PORT || 3000;

// ============================================================
// 1. CONFIGURATION & ENVIRONMENT VARIABLES
// ============================================================
const GOOGLE_CLIENT_ID = process.env.GOOGLE_CLIENT_ID;
const GOOGLE_CLIENT_SECRET = process.env.GOOGLE_CLIENT_SECRET;
const GOOGLE_REDIRECT_URI = process.env.GOOGLE_REDIRECT_URI || `http://localhost:${PORT}/auth/google/callback`;
const MONGODB_URI = process.env.MONGODB_URI;
const SESSION_SECRET = process.env.SESSION_SECRET || 'familyfolio-secret-key-999';

// ============================================================
// 2. MONGODB ATLAS CONNECTION & MODELS SETUP
// ============================================================
let GoogleToken = null;
let User = null;

if (MONGODB_URI) {
    mongoose
        .connect(MONGODB_URI)
        .then(() => {
            console.log('✅ Connected to MongoDB Atlas successfully.');
            // Initialize models from ./models folder
            const models = initModels(mongoose);
            GoogleToken = models.GoogleToken;
            User = models.User;
            console.log('✅ Models initialized: Google_Tokens and Users.');
        })
        .catch((err) => {
            console.error('❌ MongoDB Atlas connection error:', err.message);
        });
} else {
    console.warn(
        '⚠️ MONGODB_URI is not set in .env. Please configure your Atlas connection string.'
    );
}

// ============================================================
// 3. MIDDLEWARE
// ============================================================
app.use(express.json());
app.use(express.urlencoded({ extended: true }));
app.use(express.static(path.join(__dirname, 'public')));
app.use('/static', express.static(path.join(__dirname, 'static')));

app.use(
    session({
        secret: SESSION_SECRET,
        resave: false,
        saveUninitialized: false,
        cookie: {
            secure: false, // set to true if running behind HTTPS
            maxAge: 24 * 60 * 60 * 1000, // 24 hours
        },
    })
);

// Auth guard helper
const requireAuth = (req, res, next) => {
    if (!req.session || !req.session.user) {
        return res.redirect('/login');
    }
    next();
};

// Flask backend config (where app.py runs Playwright & FinancialAnalyzer)
const FLASK_PORT = process.env.FLASK_PORT || 5000;
const FLASK_HOST = process.env.FLASK_HOST || '127.0.0.1';

// Forwarding helper to connect portfolio operations to Python backend
function forwardToFlask(req, res) {
    const targetPath = req.originalUrl;
    const headers = { ...req.headers };
    headers.host = `${FLASK_HOST}:${FLASK_PORT}`;

    const options = {
        hostname: FLASK_HOST,
        port: FLASK_PORT,
        path: targetPath,
        method: req.method,
        headers: headers,
    };

    const proxyReq = http.request(options, (flaskRes) => {
        res.writeHead(flaskRes.statusCode, flaskRes.headers);
        flaskRes.pipe(res);
    });

    proxyReq.on('error', (err) => {
        console.error(`⚠️ Could not reach Flask backend at ${FLASK_HOST}:${FLASK_PORT}:`, err.message);
        res.status(502).json({
            success: false,
            error: `Python backend (app.py) is not running on port ${FLASK_PORT}. Please start 'python app.py' in a separate terminal.`,
        });
    });

    // Write body if parsed, or pipe raw stream
    if (req.body && Object.keys(req.body).length > 0) {
        if (req.is('application/json')) {
            proxyReq.write(JSON.stringify(req.body));
            proxyReq.end();
        } else if (req.is('application/x-www-form-urlencoded')) {
            proxyReq.write(new URLSearchParams(req.body).toString());
            proxyReq.end();
        } else {
            req.pipe(proxyReq);
        }
    } else {
        req.pipe(proxyReq);
    }
}

// ============================================================
// 4. ROUTES
// ============================================================

// Root redirect: If authenticated, go straight to /portfolio, otherwise /login
app.get('/', (req, res) => {
    if (req.session && req.session.user) {
        return res.redirect('/portfolio');
    }
    res.redirect('/login');
});

// Login Page
app.get('/login', (req, res) => {
    if (req.session && req.session.user) {
        return res.redirect('/portfolio');
    }
    res.sendFile(path.join(__dirname, 'public', 'login.html'));
});

// Portfolio Page & Data Route (Protected)
app.get('/portfolio', requireAuth, (req, res) => {
    // If request asks for HTML, serve the portfolio webpage
    const acceptsHtml = req.headers.accept && req.headers.accept.includes('text/html');
    if (acceptsHtml) {
        return res.sendFile(path.join(__dirname, 'public', 'portfolio.html'));
    }
    // Otherwise it's an AJAX fetch request from JavaScript for JSON portfolio metrics -> forward to Flask
    forwardToFlask(req, res);
});

// Portfolio Backend API endpoints -> forwarded to Python Flask (app.py)
app.post('/start-fetch', requireAuth, forwardToFlask);
app.post('/fetch-portfolio', requireAuth, forwardToFlask);
app.get('/job-status/:job_id', requireAuth, forwardToFlask);
app.post('/chat', requireAuth, forwardToFlask);
app.post('/reset', requireAuth, forwardToFlask);

// Redirect /dashboard to /portfolio
app.get('/dashboard', requireAuth, (req, res) => {
    res.redirect('/portfolio');
});

// API: Current logged-in user profile
app.get('/api/me', (req, res) => {
    if (req.session && req.session.user) {
        return res.json({ authenticated: true, user: req.session.user });
    }
    res.json({ authenticated: false, user: null });
});

// ============================================================
// 5. GOOGLE OAUTH 2.0 FLOW
// ============================================================

// Step 1: Redirect user to Google OAuth consent screen
app.get('/auth/google', (req, res) => {
    if (!GOOGLE_CLIENT_ID || !GOOGLE_CLIENT_SECRET) {
        return res.redirect(
            '/login?error=' +
            encodeURIComponent(
                'GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET are not set in .env'
            )
        );
    }

    const scope = ['openid', 'email', 'profile'].join(' ');
    const authUrl =
        'https://accounts.google.com/o/oauth2/v2/auth?' +
        new URLSearchParams({
            client_id: GOOGLE_CLIENT_ID,
            redirect_uri: GOOGLE_REDIRECT_URI,
            response_type: 'code',
            scope: scope,
            access_type: 'offline', // ensures refresh_token is returned
            prompt: 'consent',     // forces consent screen to guarantee refresh_token
        }).toString();

    res.redirect(authUrl);
});

// Step 2: Google OAuth Callback
app.get('/auth/google/callback', async (req, res) => {
    const { code, error } = req.query;

    if (error) {
        console.error('Google OAuth error from query:', error);
        return res.redirect('/login?error=' + encodeURIComponent(error));
    }

    if (!code) {
        return res.redirect('/login?error=' + encodeURIComponent('No authorization code provided.'));
    }

    try {
        // ----------------------------------------------------
        // A. Exchange authorization code for tokens
        // ----------------------------------------------------
        const tokenResponse = await fetch('https://oauth2.googleapis.com/token', {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: new URLSearchParams({
                code: String(code),
                client_id: GOOGLE_CLIENT_ID,
                client_secret: GOOGLE_CLIENT_SECRET,
                redirect_uri: GOOGLE_REDIRECT_URI,
                grant_type: 'authorization_code',
            }),
        });

        const tokenData = await tokenResponse.json();

        if (!tokenResponse.ok || tokenData.error) {
            console.error('Token exchange error:', tokenData);
            return res.redirect(
                '/login?error=' +
                encodeURIComponent(tokenData.error_description || tokenData.error || 'Failed to exchange token.')
            );
        }

        const { access_token, refresh_token, expires_in } = tokenData;
        const expiryTime = new Date(Date.now() + (expires_in || 3600) * 1000);

        // ----------------------------------------------------
        // B. Fetch Google User Profile using access_token
        // ----------------------------------------------------
        const userProfileResponse = await fetch('https://www.googleapis.com/oauth2/v3/userinfo', {
            headers: { Authorization: `Bearer ${access_token}` },
        });

        const profile = await userProfileResponse.json();

        if (!userProfileResponse.ok || profile.error) {
            console.error('Fetch userinfo error:', profile);
            return res.redirect(
                '/login?error=' + encodeURIComponent('Could not fetch user profile from Google.')
            );
        }

        const googleId = String(profile.sub);
        const userEmail = profile.email;
        const userName = profile.name || 'Google User';
        const userPicture = profile.picture;

        // ----------------------------------------------------
        // C. Save / Update in MongoDB Atlas according to table fields
        // ----------------------------------------------------
        if (GoogleToken && User) {

            // 1. Google_Tokens Table:
            // Columns: google_id (unique), access_token, refresh_token, expiry_time
            let tokenRecord = await GoogleToken.findOne({ google_id: googleId });

            if (tokenRecord == null) {
                tokenRecord = await GoogleToken.create({
                    google_id: googleId,
                    access_token: access_token,
                    refresh_token: refresh_token || 'no_refresh_token_provided',
                    expiry_time: expiryTime,
                });
                console.log(`✅ Stored in Google_Tokens: Google ID: ${googleId}`);
            } else {
                tokenRecord.access_token = access_token;
                if (refresh_token) {
                    tokenRecord.refresh_token = refresh_token;
                }
                tokenRecord.expiry_time = expiryTime;
                await tokenRecord.save();
                console.log(`✅ Updated Google_Tokens for Google ID: ${googleId}`);
            }

            // 2. User Table:
            // Columns: google_id (FK -> Google_tokens.google_id), name, email, created_at, updated_at

            const googleToken = await GoogleToken.findOne({
                google_id: String(googleId)
            });

            if (!googleToken) {
                throw new Error(
                    'Invalid foreign key: Google ID does not exist in Google_Tokens'
                );
            }
            let userRecord = await User.findOne({ email: userEmail });
            if (!userRecord) {
                userRecord = await User.create({
                    google_id: googleToken._id,
                    name: userName,
                    email: userEmail,
                });
                console.log(`✅ Stored in Users: Name: ${userName}, Email: ${userEmail}`);
            } else {
                userRecord.name = userName;
                userRecord.google_id = googleToken._id;
                userRecord.updated_at = new Date();
                await userRecord.save();
                console.log(`✅ Updated Users table for: ${userEmail}`);
            }
        } else {
            console.warn('⚠️ Atlas models not initialized; skipping DB write.');
        }

        // ----------------------------------------------------
        // D. Create authenticated session & redirect to PORTFOLIO page
        // ----------------------------------------------------
        req.session.user = {
            google_id: googleId,
            name: userName,
            email: userEmail,
            picture: userPicture,
            token_expiry: expiryTime,
        };

        // Redirect directly to the portfolio page (skipping dashboard)
        res.redirect('/portfolio');
    } catch (err) {
        console.dir(err.errorResponse?.errInfo?.details, {
            depth: null
        });
        console.error('OAuth callback execution error:', err);
        res.redirect('/login?error=' + encodeURIComponent(err.message));
    }
});

// Logout
app.get('/auth/logout', (req, res) => {
    req.session.destroy(() => {
        res.redirect('/login');
    });
});

// ============================================================
// 6. START SERVER
// ============================================================
app.listen(PORT, () => {
    console.log(`🚀 Financial Analyzer Node Server running at http://localhost:${PORT}`);
    console.log(`🔑 Login Page available at: http://localhost:${PORT}/login`);
});
