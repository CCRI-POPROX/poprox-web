const fs = require('fs-extra');
const path = require('path');
const marked = require('marked');
const ejs = require('ejs');

const contentDir = path.join(__dirname, 'views/data');
const templatesDir = path.join(__dirname, 'views');
const outputDir = path.join(__dirname, '_site/');
const blogDir = path.join(__dirname, 'views/blogs');
const publicDir = path.join(__dirname, 'public');

const template_data_map = {
    'home': 'index',
    'about': 'about',
    'experimenter': 'researcher',
    'newsletter': 'subscriber',
    'people': 'people',
    'contact': 'support'
}

const routeTemplateMap = {
    '/': 'home',
    '/home/': 'home',
    '/about/': 'about',
    '/experimenter/': 'experimenter',
    '/newsletter/': 'newsletter',
    '/people/': 'people',
    '/contact/': 'contact'
}

async function generateSite() {
    if (!fs.existsSync(outputDir)) {
        fs.mkdirSync(outputDir);
    }

    fs.copySync(publicDir, outputDir);

    Object.entries(routeTemplateMap).forEach(async ([route, template]) => {
        const data = template_data_map[template];
        console.log(`${route} -> ${template} -> ${data}`);
        if (data === '') {
            return
        }

        const contentFilePath = path.join(contentDir, `${data}.md`);
        const content = fs.readFileSync(contentFilePath, 'utf-8');
        const htmlContent = marked.parse(content);

        const templateFilePath = path.join(templatesDir, `${template}.ejs`);
        const templateLayout = fs.readFileSync(templateFilePath, 'utf-8');

        let renderData = {
            title: 'POPROX News',
            markdownContent: htmlContent
        }

        if (template === 'people') {
            const teamInfo = JSON.parse(fs.readFileSync(path.join(__dirname, 'public', 'data', 'teamInfo.json')));
            renderData = {
                ...renderData,
                teamInfo: teamInfo
            }
        }

        if (template === 'blog') {
            const blogFiles = fs.readdirSync(blogDir);
            // TODO: Read all the blog files and render them
            // renderData =
        }

        const renderedHtml = ejs.render(templateLayout, renderData, {
            views: [templatesDir]
        });

        let outputFilePath = path.join(outputDir, route === '/' ? 'index.html': `${route}.html`);
        if (route.endsWith("/")) {
            // create folder and write index.html instead
            if (!fs.existsSync(path.join(outputDir, route))) {
                fs.mkdirSync(path.join(outputDir, route));
            }
            outputFilePath = path.join(outputDir, route+"index.html");
        }

        // Write the output HTML file
        fs.writeFileSync(outputFilePath, renderedHtml);
    });
}

generateSite();
