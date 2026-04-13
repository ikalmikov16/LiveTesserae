import { Link } from "react-router-dom";
import { useEffect } from "react";
import "./NotFound.css";

export function NotFound() {
  useEffect(() => {
    document.title = "Live Tesserae — Page Not Found";
  }, []);

  return (
    <div className="not-found">
      <h1 className="not-found__code">404</h1>
      <p className="not-found__message">This page doesn't exist.</p>
      <div className="not-found__links">
        <Link to="/" className="not-found__link">
          Go Home
        </Link>
        <Link to="/mosaic" className="not-found__link not-found__link--secondary">
          Open Editor
        </Link>
      </div>
    </div>
  );
}
