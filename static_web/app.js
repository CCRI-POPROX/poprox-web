const express = require('express');
const path = require('path');
const fs = require('fs');
const { marked } = require('marked');

const app = express();
const port = 4000;

// Set EJS as the view engine
app.set('view engine', 'ejs');
app.set('views', path.join(__dirname, 'views'));

// Serve static files (CSS, images)
app.use(express.static(path.join(__dirname, 'public')));

// Routes for pages
app.get(['/','/home'], (req, res) => {
    res.render('home');
});

app.get('/about', (req, res) => {
    const markdownFilePath = path.join(__dirname, 'views', 'data', 'about.md'); // Change this to your file path

    fs.readFile(markdownFilePath, 'utf8', (err, data) => {
        if (err) {
            return res.status(500).send("Error reading markdown file");
        }
        const htmlContent = marked.parse(data);
        res.render('about', {
            markdownContent: htmlContent
        });
    });
});

app.get('/newsletter', (req, res) => {
    const markdownFilePath = path.join(__dirname, 'views', 'data', 'subscriber.md'); // Change this to your file path

    fs.readFile(markdownFilePath, 'utf8', (err, data) => {
        if (err) {
            return res.status(500).send("Error reading markdown file");
        }
        const htmlContent = marked.parse(data);
        res.render('newsletter', {
            markdownContent: htmlContent
        });
    });
});

app.get('/experimenter', (req, res) => {
    const markdownFilePath = path.join(__dirname, 'views', 'data', 'researcher.md'); // Change this to your file path

    fs.readFile(markdownFilePath, 'utf8', (err, data) => {
        if (err) {
            return res.status(500).send("Error reading markdown file");
        }
        const htmlContent = marked.parse(data);
        res.render('experimenter', {
            markdownContent: htmlContent
        });
    });
});


app.get('/contact', (req, res) => {
    const markdownFilePath = path.join(__dirname, 'views', 'data', 'support.md'); // Change this to your file path

    fs.readFile(markdownFilePath, 'utf8', (err, data) => {
        if (err) {
            return res.status(500).send("Error reading markdown file");
        }
        const htmlContent = marked.parse(data);
        res.render('contact', {
            markdownContent: htmlContent
        });
    });
});

const teamInfo = JSON.parse(fs.readFileSync(path.join(__dirname, 'public', 'data', 'teamInfo.json')));

app.get('/people', (req, res) => {
    res.render('people', {teamInfo});
});

app.get('/blog', (req, res) => {
    res.render('blog');
});

//blogs
app.get('/blogs', (req, res) => {
    const filePath = path.join(__dirname, 'public', 'data', 'blogs.json');
    const contentType = 'application/json';
    res.sendFile(filePath, { headers: { 'Content-Type': contentType } });
});

app.get('/blogcontent/:file', (req, res) => {
    const fileName = req.params.file;
    if (!fileName) {
        return res.status(400).json({ error: "File name is required" });
    }
    const filePath = path.join(__dirname, 'views', 'blogs', fileName);
    if (!fs.existsSync(filePath)) {
        return res.status(404).json({ error: "File not found" });
    }
    fs.readFile(filePath, 'utf8', (err, data) => {
        if (err) {
            return res.status(500).json({ error: "Error reading file" });
        }
        const htmlContent = marked(data);
        res.send(htmlContent);
    });
});

// Start server
app.listen(port, () => {
    console.log(`Server running at http://localhost:${port}/`);
});
