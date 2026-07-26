# 欢迎光临我的灵感库

## 风景园林灵感库

一个基于 React + Vite 的本地景观灵感展示网站，包含全屏首页、瀑布流素材展示、标签筛选、图片详情弹窗、管理中心和 React Bits 风格动效。

## 本地运行

```bash
npm install
npm run dev
```

打开终端中显示的本地地址，通常是：

```bash
http://127.0.0.1:5173/
```

## 构建

```bash
npm run build
```

构建产物会生成在 `dist/` 文件夹中。

## 项目结构

```text
public/              网站数据和图片素材
src/                 React 页面、组件和样式
scripts/             本地素材同步脚本
index.html           Vite 入口文件
package.json         项目依赖和脚本
vite.config.js       Vite 配置
```

## 素材说明

当前网站依赖 `public/data.js` 和 `public/小红书素材爬取/` 中的图片素材。提交到 GitHub 时需要保留 `public` 文件夹。
