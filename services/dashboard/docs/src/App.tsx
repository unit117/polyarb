import { Suspense, useCallback, useEffect, useState } from "react";
import Sidebar from "./components/Sidebar.tsx";
import { articles } from "./articles/index.ts";
import s from "./App.module.css";

function getSlugFromHash(): string {
  const hash = window.location.hash.replace(/^#\/?/, "");
  return hash || articles[0]?.slug || "";
}

export default function App() {
  const [activeSlug, setActiveSlug] = useState(getSlugFromHash);

  useEffect(() => {
    const onHashChange = () => setActiveSlug(getSlugFromHash());
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  const navigate = useCallback((slug: string) => {
    window.location.hash = `#/${slug}`;
  }, []);

  const active = articles.find((a) => a.slug === activeSlug) ?? articles[0];
  const ArticleComponent = active?.component;

  return (
    <div className={s.root}>
      <header className={s.header}>
        <span className={s.title}>PolyArb</span>
        <span className={s.subtitle}>Knowledge Base</span>
        <div className={s.spacer} />
        <a href="/" className={s.dashLink}>
          ← Dashboard
        </a>
      </header>

      <div className={s.body}>
        <Sidebar
          activeSlug={active?.slug ?? ""}
          onNavigate={navigate}
        />
        <main
          style={{
            flex: 1,
            overflowY: "auto",
            padding: "var(--space-8) var(--space-10)",
          }}
        >
          <div style={{ maxWidth: 800 }}>
            {ArticleComponent && (
              <Suspense
                fallback={
                  <div style={{ color: "var(--color-text-muted)", padding: "var(--space-8)" }}>
                    Loading...
                  </div>
                }
              >
                <ArticleComponent />
              </Suspense>
            )}
          </div>
        </main>
      </div>
    </div>
  );
}
