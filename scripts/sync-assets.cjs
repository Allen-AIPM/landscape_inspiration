const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const publicDir = path.join(root, "public");
const sourceData = path.join(root, "data.js");
const sourceImages = path.join(root, "小红书素材爬取");
const targetData = path.join(publicDir, "data.js");
const targetImages = path.join(publicDir, "小红书素材爬取");

fs.mkdirSync(publicDir, { recursive: true });

if (fs.existsSync(sourceData)) {
  fs.copyFileSync(sourceData, targetData);
}

if (fs.existsSync(sourceImages)) {
  fs.rmSync(targetImages, { recursive: true, force: true });
  fs.cpSync(sourceImages, targetImages, { recursive: true });
}
