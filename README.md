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

后续影刀爬取的新图片建议直接放入：

```text
public/小红书素材爬取/
```

如果有新的影刀 Excel 数据表，把 `数据储存.xlsx` 放入：

```text
data_sources/数据储存.xlsx
```

推荐直接运行一键更新脚本：

```bash
python scripts/update_after_crawl.py
```

也可以运行：

```bash
npm run update-data
```

Windows 上也可以双击根目录里的：

```text
一键更新网站数据.bat
```

这个脚本会自动完成：

```text
扫描新图片生成 data.js -> AI 打标 -> 收尾同步 data.js
```

运行结束后，确认页面没问题，就可以在 GitHub 仓库里提交并推送。

如果只想重新生成数据、不跑 AI：

```bash
python scripts/update_after_crawl.py --skip-ai
```

如果只想限制本次 AI 打标数量：

```bash
python scripts/update_after_crawl.py --limit 5
```

底层数据生成脚本仍然可以单独运行：

```bash
python scripts/generate_data.py
```

它会扫描图片、读取 Excel，并更新：

```text
public/data.js
```

## AI 打标

先安装 Python 依赖：

```bash
pip install -r requirements.txt
```

复制配置模板并填写 API Key：

```bash
copy ai_config.example.txt ai_config.txt
```

然后打开 `ai_config.txt`，填写：

```text
DASHSCOPE_API_KEY=你的APIKey
BAILIAN_BASE_URL=你的百炼接口URL
MODEL_NAME=qwen-vl-max
```

`ai_config.txt` 已加入 `.gitignore`，不会被提交到 GitHub。

配置完成后，推荐运行一键更新脚本：

```bash
python scripts/update_after_crawl.py
```

AI 常用参数也可以传给一键更新脚本：

```bash
python scripts/update_after_crawl.py --limit 5
python scripts/update_after_crawl.py --force
python scripts/update_after_crawl.py --retry-failed
```

AI 打标会直接更新 `public/data.js`，并在 `backup/` 中自动备份旧数据。
