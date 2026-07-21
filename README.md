# 🌸 全球花卉产业辐射与定价权 · 交互地图

> **Global Flower Industry Radiation & Pricing Power — Interactive Map**

基于 Leaflet + GeoJSON 的交互式地图，展示全球花卉产业四大空间分析图层：

| 图层 | 类型 | 数据来源 | 要素数 |
|------|------|----------|--------|
| 🌡️ 辐射密度面 (IDW插值) | 面 (Polygon) | ArcGIS IDW 空间插值 | 11 |
| 🔬 核密度分析 | 面 (Polygon) | ArcGIS Kernel Density | 8 |
| 🔗 贸易网络线 (OD) | 线 (LineString) | 昆明 → 全球目的地 OD 矩阵 | 1198 |
| ⭐ 定价权等级 | 点 (Point) | 全球花卉拍卖市场 / 批发市场 | 30 |

---

## 🚀 快速部署到 GitHub Pages

### 方法一：命令行

```bash
# 1. 在 GitHub 上创建新仓库，假设名为 flower-map

# 2. 推送代码
cd "Desktop/flower"
git add index.html geojson/ .gitignore README.md
git commit -m "feat: interactive flower industry map"
git branch -M main
git remote add origin https://github.com/<你的用户名>/flower-map.git
git push -u origin main
```

### 方法二：GitHub Desktop / VS Code

如果你的编辑器提示缺少 Git，在 VS Code 中打开此文件夹，用 Source Control 面板提交并发布到 GitHub。

### 3. 启用 GitHub Pages

进入仓库 → **Settings** → **Pages**：
- **Source**: Deploy from a branch
- **Branch**: `main` / `(root)`
- 点击 **Save**

1-2 分钟后访问 `https://<你的用户名>.github.io/flower-map/`

---

## 🗺️ 功能说明

- **图层切换**: 右上方面板可独立开关 4 个图层
- **底图切换**: 右下角切换浅色地图 / 卫星影像
- **悬停弹窗**: 鼠标悬停在要素上显示属性信息
- **点击详情**: 点击市场点位查看完整信息（含中英文名、城市、类型、说明）
- **市场标签**: 可开关全球花卉市场名称标注
- **自适应缩放**: 自动适配所有数据范围

---

## 📁 文件结构

```
├── index.html              # 主地图页面
├── geojson/                # 转换后的 GeoJSON 数据
│   ├── B1_IDW插值.geojson
│   ├── B1_核密度分析.geojson
│   ├── B1_OD网络线.geojson
│   └── B1_定价权等级.geojson
├── B1_全球辐射/            # 原始 Shapefile（不上传）
└── README.md
```

---

## 🔧 技术栈

- [Leaflet.js](https://leafletjs.com/) — 开源交互地图库
- [CARTO](https://carto.com/) / [Esri](https://www.esri.com/) — 底图瓦片
- GeoJSON — 开放地理数据格式
- GitHub Pages — 免费静态网站托管
