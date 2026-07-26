import { useEffect, useMemo, useState } from "react";
import {
  ChevronDown,
  Clock,
  ExternalLink,
  Eye,
  Heart,
  ImageOff,
  MapPin,
  MessageCircle,
  RotateCcw,
  Search,
  SlidersHorizontal,
  Star,
  ThumbsUp,
  X,
} from "lucide-react";
import TargetCursor from "./components/TargetCursor.jsx";
import PillNav from "./components/PillNav.jsx";
import CardSwap, { Card } from "./components/CardSwap.jsx";
import SplitText from "./components/SplitText.jsx";

const categories = [
  "全部",
  "居住与社区",
  "商业与园区",
  "公共与公园",
  "滨水与生态",
  "文旅与度假",
  "水景与构筑",
  "植物与植物造景",
  "表达与分析图",
];

const defaultFilters = {
  keyword: "",
  landscape: "",
  imageType: "",
  platform: "",
  style: "",
  material: "",
  space: "",
  sort: "default",
};

function normalizeImageUrl(url) {
  if (!url) return "";
  return url.startsWith("./") ? url.replace("./", "/") : url;
}

function formatDate(value, withTime = false) {
  if (!value) return "";
  const date = new Date(String(value).replace(" ", "T"));
  if (Number.isNaN(date.getTime())) return value;
  const day = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
  if (!withTime) return day;
  return `${day} ${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
}

function uniqueOptions(items, getter) {
  return [...new Set(items.flatMap((item) => getter(item)).filter(Boolean))].sort((a, b) =>
    String(a).localeCompare(String(b), "zh-CN"),
  );
}

function categoryMatches(item, category) {
  if (category === "全部") return true;
  const lt = item.landscape_type || "";
  const it = item.image_type || "";
  const elements = Array.isArray(item.element_tags) ? item.element_tags : [];
  const materials = Array.isArray(item.material_tags) ? item.material_tags : [];
  const has = (arr, value) => arr.includes(value);

  if (category === "居住与社区") return lt === "居住区景观";
  if (category === "商业与园区") return lt === "商业景观" || lt === "办公园区景观";
  if (category === "公共与公园") return lt === "公园景观" || lt === "城市公共空间" || lt === "校园景观";
  if (category === "滨水与生态") return ["滨水景观", "山地与自然景观", "乡村景观", "生态修复景观"].includes(lt);
  if (category === "文旅与度假") return lt === "文旅景观";
  if (category === "水景与构筑") return lt === "滨水景观" || ["水体", "景观小品", "园路", "铺装"].some((tag) => has(elements, tag));
  if (category === "植物与植物造景") return lt === "植物景观" || has(elements, "植物") || has(materials, "植物材料");
  if (category === "表达与分析图") {
    return ["分析图", "总平面图", "功能分区图", "植物配置图", "竖向设计图", "节点详图", "剖面图", "轴测图", "流程图", "图表"].includes(it);
  }
  return true;
}

function searchableText(item) {
  const fields = [
    item.title,
    item.file_name,
    item.source_user,
    item.source_title,
    item.source_platform,
    item.landscape_type,
    item.image_type,
    item.ai_description,
  ];
  ["style_tags", "material_tags", "color_tags", "space_tags", "element_tags", "keywords"].forEach((key) => {
    if (Array.isArray(item[key])) fields.push(...item[key]);
  });
  return fields.filter(Boolean).join(" ").toLowerCase();
}

function findSimilarItems(current, allItems, limit = 4) {
  if (!current) return [];
  const tags = [
    ...(current.style_tags || []),
    ...(current.material_tags || []),
    ...(current.space_tags || []),
    current.landscape_type,
  ].filter(Boolean);

  return allItems
    .filter((item) => item.id !== current.id)
    .map((item) => {
      const otherTags = [
        ...(item.style_tags || []),
        ...(item.material_tags || []),
        ...(item.space_tags || []),
        item.landscape_type,
      ].filter(Boolean);
      return { item, score: tags.filter((tag) => otherTags.includes(tag)).length };
    })
    .filter((entry) => entry.score > 0)
    .sort((a, b) => b.score - a.score)
    .slice(0, limit)
    .map((entry) => entry.item);
}

function App() {
  const [items, setItems] = useState(() => (Array.isArray(window.inspirationItems) ? window.inspirationItems : []));
  const [category, setCategory] = useState("全部");
  const [filters, setFilters] = useState(defaultFilters);
  const [detailItem, setDetailItem] = useState(null);
  const [zoomed, setZoomed] = useState(false);
  const [activeView, setActiveView] = useState("library");
  const [activeHref, setActiveHref] = useState("#hero");

  useEffect(() => {
    const close = (event) => {
      if (event.key === "Escape") setDetailItem(null);
    };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, []);

  useEffect(() => {
    document.body.style.overflow = detailItem ? "hidden" : "";
    setZoomed(false);
  }, [detailItem]);

  const options = useMemo(
    () => ({
      landscapes: uniqueOptions(items, (item) => [item.landscape_type]),
      imageTypes: uniqueOptions(items, (item) => [item.image_type]),
      platforms: uniqueOptions(items, (item) => [item.source_platform]),
      styles: uniqueOptions(items, (item) => item.style_tags || []),
      materials: uniqueOptions(items, (item) => item.material_tags || []),
      spaces: uniqueOptions(items, (item) => item.space_tags || []),
    }),
    [items],
  );

  const filteredItems = useMemo(() => {
    const keyword = filters.keyword.trim().toLowerCase();
    const result = items.filter((item) => {
      if (!categoryMatches(item, category)) return false;
      if (filters.landscape && item.landscape_type !== filters.landscape) return false;
      if (filters.imageType && item.image_type !== filters.imageType) return false;
      if (filters.platform && item.source_platform !== filters.platform) return false;
      if (filters.style && !(item.style_tags || []).includes(filters.style)) return false;
      if (filters.material && !(item.material_tags || []).includes(filters.material)) return false;
      if (filters.space && !(item.space_tags || []).includes(filters.space)) return false;
      if (keyword && !searchableText(item).includes(keyword)) return false;
      return true;
    });

    if (filters.sort === "newest") result.sort((a, b) => String(b.created_at || "").localeCompare(String(a.created_at || "")));
    if (filters.sort === "oldest") result.sort((a, b) => String(a.created_at || "").localeCompare(String(b.created_at || "")));
    if (filters.sort === "title") result.sort((a, b) => String(a.title || "").localeCompare(String(b.title || ""), "zh-CN"));
    if (filters.sort === "favorite") result.sort((a, b) => Number(Boolean(b.favorite)) - Number(Boolean(a.favorite)));
    return result;
  }, [category, filters, items]);

  const heroCards = useMemo(() => items.filter((item) => item.image_url).slice(0, 5), [items]);
  const totalLikes = items.reduce((sum, item) => sum + (item.like_count || 0), 0);
  const reviewed = items.filter((item) => item.tagging_status === "success" || item.tagging_status === "completed").length;

  function updateFilter(key, value) {
    setFilters((current) => ({ ...current, [key]: value }));
  }

  function resetFilters() {
    setCategory("全部");
    setFilters(defaultFilters);
  }

  function toggleFlag(target, key) {
    setItems((current) => current.map((item) => (item.id === target.id ? { ...item, [key]: !item[key] } : item)));
  }

  function handleNavigate(event, item) {
    event.preventDefault();
    setActiveHref(item.href);
    if (item.href === "#admin") {
      setActiveView("admin");
      window.history.replaceState(null, "", "#admin");
      window.scrollTo({ top: 0, behavior: "smooth" });
      return;
    }

    setActiveView("library");
    window.history.replaceState(null, "", item.href);
    requestAnimationFrame(() => {
      const target = document.querySelector(item.href === "#filters" ? "#gallery" : item.href);
      if (target) target.scrollIntoView({ behavior: "smooth", block: item.href === "#hero" ? "start" : "start" });
    });
  }

  return (
    <div className="app-shell">
      <TargetCursor targetSelector=".cursor-target" cursorColor="#ffffff" cursorColorOnTarget="#8fd4b1" />
      <PillNav
        activeHref={activeView === "admin" ? "#admin" : activeHref}
        onNavigate={handleNavigate}
        items={[
          { label: "首页", href: "#hero" },
          { label: "灵感瀑布流", href: "#gallery" },
          { label: "标签筛选", href: "#filters" },
          { label: "管理中心", href: "#admin" },
        ]}
      />

      {activeView === "library" ? (
        <>
          <header id="hero" className="hero" style={{ "--hero-image": 'url("/hero-landscape.jpeg")' }}>
            <div className="hero-inner">
              <section className="hero-copy">
                <SplitText tag="div" className="hero-kicker" text="Landscape Inspiration System" delay={28} duration={0.7} splitType="words" />
                <div className="hero-title" aria-label="让景观灵感 自动被你看见">
                  <SplitText tag="span" className="hero-title-line" text="让景观灵感" delay={34} duration={0.9} splitType="chars" />
                  <SplitText tag="span" className="hero-title-line" text="自动被你看见" delay={34} duration={0.9} splitType="chars" />
                </div>
                <SplitText
                  tag="p"
                  className="hero-subtitle"
                  text="把小红书素材、AI 标签和本地图片整理成一个可筛选、可展开、可回看的景观灵感库。"
                  delay={18}
                  duration={0.65}
                  splitType="words"
                  from={{ opacity: 0, y: 18 }}
                />
                <div className="hero-stats">
                  <span>
                    <SplitText tag="strong" text={String(items.length)} delay={20} duration={0.55} splitType="chars" />
                    <SplitText tag="em" text="张素材" delay={18} duration={0.55} splitType="chars" />
                  </span>
                  <span>
                    <SplitText tag="strong" text={String(reviewed)} delay={20} duration={0.55} splitType="chars" />
                    <SplitText tag="em" text="已标注" delay={18} duration={0.55} splitType="chars" />
                  </span>
                  <span>
                    <SplitText tag="strong" text={String(totalLikes)} delay={20} duration={0.55} splitType="chars" />
                    <SplitText tag="em" text="原帖点赞" delay={18} duration={0.55} splitType="chars" />
                  </span>
                </div>
              </section>

              <section className="hero-gallery" aria-label="首页图集展示">
                <CardSwap width={420} height={320} cardDistance={44} verticalDistance={48} delay={3600} pauseOnHover skewAmount={4} easing="elastic">
                  {heroCards.map((item) => (
                    <Card key={item.id} customClass="hero-swap-card cursor-target">
                      <img src={normalizeImageUrl(item.image_url)} alt={item.title || item.file_name || "景观素材"} />
                      <div className="swap-card-caption">
                        <strong>{item.title || item.file_name || "未命名"}</strong>
                        <span>{item.landscape_type || item.image_type || "景观灵感"}</span>
                      </div>
                    </Card>
                  ))}
                </CardSwap>
              </section>
            </div>
          </header>

          <section id="filters" className="filter-dock" aria-label="素材筛选">
            <div className="category-row">
              {categories.map((cat) => (
                <button key={cat} className={cat === category ? "cat-item active cursor-target" : "cat-item cursor-target"} onClick={() => setCategory(cat)}>
                  {cat}
                </button>
              ))}
            </div>

            <div className="filter-row">
              <label className="search-box cursor-target">
                <Search size={16} />
                <input value={filters.keyword} onChange={(event) => updateFilter("keyword", event.target.value)} placeholder="搜索标题、用户、标签、描述..." />
              </label>
              <Select label="景观类型" value={filters.landscape} options={options.landscapes} onChange={(value) => updateFilter("landscape", value)} />
              <Select label="图片类型" value={filters.imageType} options={options.imageTypes} onChange={(value) => updateFilter("imageType", value)} />
              <Select label="来源平台" value={filters.platform} options={options.platforms} onChange={(value) => updateFilter("platform", value)} />
              <Select label="设计风格" value={filters.style} options={options.styles} onChange={(value) => updateFilter("style", value)} />
              <Select label="主要材料" value={filters.material} options={options.materials} onChange={(value) => updateFilter("material", value)} />
              <Select label="空间类型" value={filters.space} options={options.spaces} onChange={(value) => updateFilter("space", value)} />
              <label className="select-wrap cursor-target">
                <SlidersHorizontal size={15} />
                <select value={filters.sort} onChange={(event) => updateFilter("sort", event.target.value)}>
                  <option value="default">默认排序</option>
                  <option value="newest">最新优先</option>
                  <option value="oldest">最早优先</option>
                  <option value="title">标题排序</option>
                  <option value="favorite">收藏优先</option>
                </select>
                <ChevronDown size={14} />
              </label>
              <button className="btn-reset cursor-target" onClick={resetFilters}>
                <RotateCcw size={15} />
                重置
              </button>
              <div className="filter-count">
                共 <strong>{filteredItems.length}</strong> 张 / {items.length} 张
              </div>
            </div>
          </section>

          <main id="gallery" className="content-wrap">
            {filteredItems.length > 0 ? (
              <section className="masonry" aria-label="图片瀑布流">
                {filteredItems.map((item) => (
                  <ImageCard key={item.id} item={item} onOpen={() => setDetailItem(item)} onToggleFlag={toggleFlag} />
                ))}
              </section>
            ) : (
              <section className="empty-state">
                <ImageOff size={48} />
                <h2>暂无匹配素材</h2>
                <p>换一个分类或减少筛选条件后再试。</p>
              </section>
            )}
          </main>
        </>
      ) : (
        <main id="admin" className="admin-view">
          <AdminCenter items={items} />
        </main>
      )}

      {detailItem && (
        <DetailModal
          item={detailItem}
          items={items}
          zoomed={zoomed}
          onZoom={() => setZoomed((value) => !value)}
          onClose={() => setDetailItem(null)}
          onOpenItem={setDetailItem}
        />
      )}
    </div>
  );
}

function Select({ label, value, options, onChange }) {
  return (
    <label className="select-wrap cursor-target">
      <select value={value} onChange={(event) => onChange(event.target.value)} aria-label={label}>
        <option value="">{label}</option>
        {options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
      <ChevronDown size={14} />
    </label>
  );
}

function ImageCard({ item, onOpen, onToggleFlag }) {
  const [failed, setFailed] = useState(false);
  const styleTags = Array.isArray(item.style_tags) ? item.style_tags : [];
  return (
    <article className="card cursor-target" onClick={onOpen}>
      {item.favorite && <span className="card-fav-badge">收藏</span>}
      {item.liked && (
        <span className="card-like-badge">
          <Heart size={14} fill="currentColor" />
        </span>
      )}
      <div className="card-img-wrapper">
        {!failed && item.image_url ? (
          <img className="card-img" src={normalizeImageUrl(item.image_url)} alt={item.title || item.file_name || "景观素材"} loading="lazy" onError={() => setFailed(true)} />
        ) : (
          <div className="card-img-placeholder">
            <ImageOff size={30} />
            <span>图片加载失败</span>
          </div>
        )}
        <div className="card-overlay">
          <button className={item.favorite ? "card-action active cursor-target" : "card-action cursor-target"} onClick={(event) => { event.stopPropagation(); onToggleFlag(item, "favorite"); }} aria-label="收藏">
            <Star size={17} fill={item.favorite ? "currentColor" : "none"} />
          </button>
          <button className={item.liked ? "card-action active cursor-target" : "card-action cursor-target"} onClick={(event) => { event.stopPropagation(); onToggleFlag(item, "liked"); }} aria-label="喜欢">
            <Heart size={17} fill={item.liked ? "currentColor" : "none"} />
          </button>
          <button className="card-action cursor-target" onClick={(event) => { event.stopPropagation(); onOpen(); }} aria-label="查看详情">
            <Eye size={17} />
          </button>
        </div>
      </div>
      <div className="card-body">
        <h2 className="card-title">{item.title || item.file_name || "未命名"}</h2>
        <div className="card-meta">
          {item.landscape_type && <span className="card-tag">{item.landscape_type}</span>}
          {item.image_type && item.image_type !== "待AI打标" && <span className="card-tag warm">{item.image_type}</span>}
          {styleTags.slice(0, 2).map((tag) => (
            <span className="card-tag gray" key={tag}>
              {tag}
            </span>
          ))}
        </div>
        <div className="card-info">
          {item.source_platform && (
            <span>
              <MapPin size={12} />
              {item.source_platform}
            </span>
          )}
          {item.crawl_time && (
            <span>
              <Clock size={12} />
              {formatDate(item.crawl_time)}
            </span>
          )}
        </div>
        {(item.like_count > 0 || item.collect_count > 0 || item.comment_count > 0) && (
          <div className="card-stats">
            {item.like_count > 0 && <Stat icon={<ThumbsUp size={13} />} value={item.like_count} />}
            {item.collect_count > 0 && <Stat icon={<Star size={13} />} value={item.collect_count} />}
            {item.comment_count > 0 && <Stat icon={<MessageCircle size={13} />} value={item.comment_count} />}
          </div>
        )}
      </div>
    </article>
  );
}

function Stat({ icon, value }) {
  return (
    <span className="stat">
      {icon}
      <strong>{value}</strong>
    </span>
  );
}

function AdminCenter({ items }) {
  const stats = useMemo(() => {
    const pending = items.filter((item) => (item.tagging_status || "pending") === "pending").length;
    const completed = items.filter((item) => item.tagging_status === "success" || item.tagging_status === "completed").length;
    return [
      ["图片总数", items.length, "本地扫描图片"],
      ["Excel 匹配", items.filter((item) => item.excel_matched).length, "已匹配来源信息"],
      ["待 AI 打标", pending, "尚未完成标注"],
      ["AI 已完成", completed, "标注完成图片"],
      ["需人工审核", items.filter((item) => item.need_review).length, "低置信度素材"],
      ["总点赞数", items.reduce((sum, item) => sum + (item.like_count || 0), 0), "原帖点赞汇总"],
      ["总收藏数", items.reduce((sum, item) => sum + (item.collect_count || 0), 0), "原帖收藏汇总"],
      ["本地收藏", items.filter((item) => item.favorite).length, "本地标记收藏"],
    ];
  }, [items]);

  return (
    <section id="admin" className="admin-panel">
      <div className="admin-heading">
        <span>Management</span>
        <h2>管理中心</h2>
      </div>
      <div className="admin-stats">
        {stats.map(([label, value, sub]) => (
          <article className="stat-card" key={label}>
            <div className="stat-label">{label}</div>
            <div className="stat-value">{value}</div>
            <div className="stat-sub">{sub}</div>
          </article>
        ))}
      </div>
      <div className="admin-table-wrap">
        <table className="admin-table">
          <thead>
            <tr>
              <th>标题</th>
              <th>文件名</th>
              <th>来源平台</th>
              <th>图片类型</th>
              <th>AI 状态</th>
              <th>置信度</th>
              <th>点赞</th>
              <th>收藏</th>
              <th>评论</th>
              <th>需审核</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.id}>
                <td>{item.title || item.file_name || "-"}</td>
                <td>{item.file_name || "-"}</td>
                <td>{item.source_platform || "-"}</td>
                <td>{item.image_type || "-"}</td>
                <td>
                  <span className={`status-badge status-${statusClass(item.tagging_status)}`}>{statusText(item.tagging_status)}</span>
                </td>
                <td>{Math.round((item.confidence || 0) * 100)}%</td>
                <td>{item.like_count || 0}</td>
                <td>{item.collect_count || 0}</td>
                <td>{item.comment_count || 0}</td>
                <td>{item.need_review ? "是" : "否"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function DetailModal({ item, items, zoomed, onZoom, onClose, onOpenItem }) {
  const [failed, setFailed] = useState(false);
  const similar = findSimilarItems(item, items);
  const sameLandscape = items.filter((entry) => entry.id !== item.id && entry.landscape_type && entry.landscape_type === item.landscape_type).slice(0, 4);

  useEffect(() => {
    setFailed(false);
  }, [item]);

  return (
    <div className="modal-overlay show" onMouseDown={onClose}>
      <div className="modal" onMouseDown={(event) => event.stopPropagation()} role="dialog" aria-modal="true" aria-label="图片详情">
        <header className="modal-header">
          <h2>{item.title || item.file_name || "详情"}</h2>
          <button className="modal-close cursor-target" onClick={onClose} aria-label="关闭详情">
            <X size={20} />
          </button>
        </header>
        <div className="modal-body">
          <aside className="modal-left">
            <div className="detail-img-container cursor-target">
              {!failed && item.image_url ? (
                <img className={zoomed ? "zoomed" : ""} src={normalizeImageUrl(item.image_url)} alt={item.title || "景观素材"} onClick={onZoom} onError={() => setFailed(true)} />
              ) : (
                <div className="detail-img-placeholder">
                  <ImageOff size={44} />
                  <span>图片加载失败</span>
                </div>
              )}
            </div>
            <div className="detail-img-info">
              {item.file_name && (
                <div>
                  <span>文件名:</span>
                  <strong>{item.file_name}</strong>
                </div>
              )}
              {item.relative_path && (
                <div>
                  <span>本地路径:</span>
                  <strong>{item.relative_path}</strong>
                </div>
              )}
              <div>
                <span>点击图片可缩放查看</span>
              </div>
            </div>
          </aside>

          <section className="modal-center">
            <DetailSection title="基本信息">
              <DetailRow label="图片标题" value={item.title} />
              <DetailRow label="来源用户名" value={item.source_user} />
              <DetailRow label="来源平台" value={item.source_platform} />
              <DetailRow label="原始标题" value={item.source_title} />
              <DetailRow label="爬取时间" value={formatDate(item.crawl_time, true)} />
              <DetailRow label="景观类型" value={item.landscape_type} />
              <DetailRow label="图片类型" value={item.image_type} />
            </DetailSection>

            <DetailSection title="互动数据">
              <DetailRow label="点赞数" value={item.like_count || 0} />
              <DetailRow label="收藏数" value={item.collect_count || 0} />
              <DetailRow label="评论数" value={item.comment_count || 0} />
            </DetailSection>

            <DetailSection title="标签信息">
              <TagRow label="风格标签" tags={item.style_tags} />
              <TagRow label="材料标签" tags={item.material_tags} />
              <TagRow label="色彩标签" tags={item.color_tags} />
              <TagRow label="空间标签" tags={item.space_tags} />
              <TagRow label="设计元素" tags={item.element_tags} />
              <TagRow label="关键词" tags={item.keywords} />
            </DetailSection>

            <DetailSection title="AI 标注">
              <DetailRow label="AI 描述" value={item.ai_description} />
              <div className="detail-row">
                <div className="dl-label">AI 置信度</div>
                <div className="dl-value">
                  {Math.round((item.confidence || 0) * 100)}%
                  <div className="confidence-bar">
                    <div className="confidence-fill" style={{ width: `${Math.round((item.confidence || 0) * 100)}%` }} />
                  </div>
                </div>
              </div>
              <DetailRow label="需人工审核" value={item.need_review ? "是" : "否"} />
              <DetailRow label="AI 状态" value={statusText(item.tagging_status)} />
            </DetailSection>

            {item.source_url && (
              <a className="btn-source-url cursor-target" href={item.source_url} target="_blank" rel="noreferrer">
                <ExternalLink size={15} />
                查看原始网页
              </a>
            )}
          </section>

          <aside className="modal-right">
            <RecoList title="相似灵感推荐" items={similar} onOpen={onOpenItem} />
            <RecoList title="同景观类型" items={sameLandscape} onOpen={onOpenItem} />
          </aside>
        </div>
      </div>
    </div>
  );
}

function statusText(status) {
  const map = {
    pending: "待处理",
    completed: "已完成",
    success: "已完成",
    error: "错误",
    processing: "处理中",
  };
  return map[status] || status || "待处理";
}

function statusClass(status) {
  if (status === "success" || status === "completed") return "completed";
  if (status === "error") return "error";
  return "pending";
}

function DetailSection({ title, children }) {
  return (
    <div className="detail-section">
      <h3>{title}</h3>
      {children}
    </div>
  );
}

function DetailRow({ label, value }) {
  const empty = value === undefined || value === null || value === "";
  return (
    <div className="detail-row">
      <div className="dl-label">{label}</div>
      <div className={empty ? "dl-value empty" : "dl-value"}>{empty ? "-" : String(value)}</div>
    </div>
  );
}

function TagRow({ label, tags }) {
  const values = Array.isArray(tags) ? tags : [];
  return (
    <div className="detail-row">
      <div className="dl-label">{label}</div>
      <div className={values.length ? "dl-value" : "dl-value empty"}>
        {values.length ? (
          <div className="detail-tags">
            {values.map((tag) => (
              <span className="detail-tag" key={tag}>
                {tag}
              </span>
            ))}
          </div>
        ) : (
          "-"
        )}
      </div>
    </div>
  );
}

function RecoList({ title, items, onOpen }) {
  return (
    <div className="reco-section">
      <h3>{title}</h3>
      {items.length ? (
        items.map((item) => (
          <button className="reco-item cursor-target" key={item.id} onClick={() => onOpen(item)}>
            <img src={normalizeImageUrl(item.image_url)} alt="" loading="lazy" />
            <span>
              <strong>{item.title || item.file_name || "未命名"}</strong>
              <em>{item.source_platform || item.landscape_type || "本地素材"}</em>
            </span>
          </button>
        ))
      ) : (
        <p className="reco-empty">暂无推荐</p>
      )}
    </div>
  );
}

export default App;
