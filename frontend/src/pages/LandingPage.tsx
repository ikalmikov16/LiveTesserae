import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Grid3X3,
  Sparkles,
  Users,
  Scan,
  MousePointerClick,
  Paintbrush,
  Zap,
  Heart,
} from "lucide-react";
import { getMosaicStats, type MosaicStats } from "../api/mosaic";
import { getMosaicOverviewUrl, getOverviewVersion } from "../api/chunks";
import "./LandingPage.css";

const TOTAL_TILES = 1_000_000;
const TILE_SIZE = 32;
const TOTAL_PIXELS = TOTAL_TILES * TILE_SIZE * TILE_SIZE;

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

  const statsLoaded = stats !== null;
  const totalTiles = useCountUp(statsLoaded ? TOTAL_TILES : 0);
  const totalEdits = useCountUp(stats?.total_edits ?? 0);
  const uniqueEditors = useCountUp(stats?.unique_editors ?? 0);
  const totalPixels = useCountUp(statsLoaded ? TOTAL_PIXELS : 0, 2000);

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
            <Grid3X3 size={20} className="landing-page__stat-icon" />
            <span className="landing-page__stat-value">{formatNumber(totalTiles)}</span>
            <span className="landing-page__stat-label">total tiles</span>
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
          <div className="landing-page__stat glass-panel">
            <Scan size={20} className="landing-page__stat-icon" />
            <span className="landing-page__stat-value">{formatNumber(totalPixels)}</span>
            <span className="landing-page__stat-label">total pixels</span>
          </div>
        </div>
      )}

      {statsError && !stats && (
        <p className="landing-page__stats-error">Stats unavailable right now</p>
      )}

      <section className="landing-page__how-it-works">
        <h2 className="landing-page__section-title">How It Works</h2>
        <div className="landing-page__steps">
          <div className="landing-page__step glass-panel">
            <MousePointerClick size={28} className="landing-page__step-icon" />
            <h3 className="landing-page__step-title">Pick a tile</h3>
            <p className="landing-page__step-desc">
              Explore a mosaic of 1 million tiles arranged on a 1,000 &times; 1,000 grid
            </p>
          </div>
          <div className="landing-page__step glass-panel">
            <Paintbrush size={28} className="landing-page__step-icon" />
            <h3 className="landing-page__step-title">Paint it</h3>
            <p className="landing-page__step-desc">
              Each tile is a tiny 32 &times; 32 pixel canvas &mdash; your own mini artwork
            </p>
          </div>
          <div className="landing-page__step glass-panel">
            <Zap size={28} className="landing-page__step-icon" />
            <h3 className="landing-page__step-title">See it live</h3>
            <p className="landing-page__step-desc">
              Your changes appear instantly for everyone in real time
            </p>
          </div>
          <div className="landing-page__step glass-panel">
            <Heart size={28} className="landing-page__step-icon" />
            <h3 className="landing-page__step-title">Build together</h3>
            <p className="landing-page__step-desc">
              Every edit becomes part of a massive collaborative artwork
            </p>
          </div>
        </div>
      </section>

      <button className="landing-page__cta" onClick={() => navigate("/mosaic")}>
        Start Creating
      </button>
    </div>
  );
}
