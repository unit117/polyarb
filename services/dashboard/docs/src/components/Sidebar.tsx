import { memo, useMemo, useState } from "react";
import { articles, categories } from "../articles/index.ts";
import s from "./Sidebar.module.css";

interface Props {
  activeSlug: string;
  onNavigate: (slug: string) => void;
}

export default memo(function Sidebar({ activeSlug, onNavigate }: Props) {
  const [search, setSearch] = useState("");
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});

  const filtered = useMemo(() => {
    if (!search.trim()) return articles;
    const q = search.toLowerCase();
    return articles.filter(
      (a) =>
        a.title.toLowerCase().includes(q) ||
        a.category.toLowerCase().includes(q),
    );
  }, [search]);

  const visibleCategories = useMemo(() => {
    const cats = new Set(filtered.map((a) => a.category));
    return categories.filter((c) => cats.has(c));
  }, [filtered]);

  const toggleCategory = (cat: string) => {
    setCollapsed((prev) => ({ ...prev, [cat]: !prev[cat] }));
  };

  return (
    <aside className={s.sidebar}>
      <div className={s.search}>
        <input
          className={s.searchInput}
          type="text"
          placeholder="Search articles..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>
      <nav className={s.nav}>
        {visibleCategories.map((cat) => {
          const isCollapsed = collapsed[cat] && !search.trim();
          const catArticles = filtered.filter((a) => a.category === cat);
          return (
            <div key={cat}>
              <div
                className={s.category}
                onClick={() => toggleCategory(cat)}
              >
                <span
                  className={`${s.categoryArrow} ${!isCollapsed ? s.categoryArrowOpen : ""}`}
                >
                  ▸
                </span>
                {cat}
              </div>
              {!isCollapsed &&
                catArticles.map((article) => (
                  <button
                    key={article.slug}
                    className={`${s.navItem} ${activeSlug === article.slug ? s.navItemActive : ""}`}
                    onClick={() => onNavigate(article.slug)}
                  >
                    {article.title}
                  </button>
                ))}
            </div>
          );
        })}
      </nav>
    </aside>
  );
});
