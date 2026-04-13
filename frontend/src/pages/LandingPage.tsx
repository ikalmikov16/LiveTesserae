import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Brush, Users, Sparkles } from "lucide-react";
import { getMosaicStats, type MosaicStats } from "../api/mosaic";
import { getMosaicOverviewUrl, getOverviewVersion } from "../api/chunks";
import "./LandingPage.css";

function useCountUp(target: number, durationMs: number = 1500): number {
  const [value, setValue] = useState(0);
  const startedRef = useRef(false);

  useEffect(() => {
    if (target <= 0 || startedRef.current) return;
    startedRef.current = true;

    const startTime = performance.now();
    const animate = (now: number) => {
      const elapsed = now - startTime;
      const t = Math.min(elapsed / durationMs, 1);
      const eased = 1 - Math.pow(1 - t, 3);
      setValue(Math.round(target * eased));
      if (t < 1) requestAnimationFrame(animate);
    };
    requestAnimationFrame(animate);
  }, [target, durationMs]);

  return value;
}

const formatNumber = (n: number) => new Intl.NumberFormat().format(n);

export function LandingPage() {
  const navigate = useNavigate();
  const [stats, setStats] = useState<MosaicStats | null>(null);
  const [statsError, setStatsError] = useState(false);
  const [overviewUrl, setOverviewUrl] = useState<string | null>(null);
  const [overviewLoading, setOverviewLoading] = useState(true);

  useEffect(() => {
    document.title = "Live Tesserae";
  }, []);

  useEffect(() => {
    getMosaicStats()
      .then(setStats)
      .catch(() => setStatsError(true));

    getOverviewVersion()
      .then((info) => setOverviewUrl(getMosaicOverviewUrl(info.version)))
      .catch(() => setOverviewUrl(getMosaicOverviewUrl()));
  }, []);

  const editedTiles = useCountUp(stats?.edited_tiles ?? 0);
  const totalEdits = useCountUp(stats?.total_edits ?? 0);
  const uniqueEditors = useCountUp(stats?.unique_editors ?? 0);

  return (
    <div className="landing-page">
      <header className="landing-page__header">
        <h1 className="landing-page__title">Live Tesserae</h1>
        <p className="landing-page__tagline">A collaborative mosaic made by everyone</p>
      </header>

      <div className="landing-page__mosaic">
        {overviewUrl ? (
          <img
            src={overviewUrl}
            alt="Live Tesserae mosaic overview"
            className="landing-page__overview-img"
            draggable={false}
            onLoad={() => setOverviewLoading(false)}
            onError={() => setOverviewLoading(false)}
            style={overviewLoading ? { visibility: "hidden", position: "absolute" } : undefined}
          />
        ) : null}
        {overviewLoading && (
          <div className="landing-page__overview-placeholder">
            <div className="landing-page__spinner" />
          </div>
        )}
      </div>

      {stats && (
        <div className="landing-page__stats">
          <div className="landing-page__stat glass-panel">
            <Brush size={20} className="landing-page__stat-icon" />
            <span className="landing-page__stat-value">{formatNumber(editedTiles)}</span>
            <span className="landing-page__stat-label">tiles painted</span>
          </div>
          <div className="landing-page__stat glass-panel">
            <Sparkles size={20} className="landing-page__stat-icon" />
            <span className="landing-page__stat-value">{formatNumber(totalEdits)}</span>
            <span className="landing-page__stat-label">total edits</span>
          </div>
          <div className="landing-page__stat glass-panel">
            <Users size={20} className="landing-page__stat-icon" />
            <span className="landing-page__stat-value">{formatNumber(uniqueEditors)}</span>
            <span className="landing-page__stat-label">artists</span>
          </div>
        </div>
      )}

      {statsError && !stats && (
        <p className="landing-page__stats-error">Stats unavailable right now</p>
      )}

      <button className="landing-page__cta" onClick={() => navigate("/mosaic")}>
        Start Creating
      </button>
    </div>
  );
}
