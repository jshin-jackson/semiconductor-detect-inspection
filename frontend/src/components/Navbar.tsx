import { NavLink } from "react-router-dom";

const NAV_ITEMS = [
  { to: "/", label: "Dashboard" },
  { to: "/inspect", label: "Inspect" },
  { to: "/history", label: "History" },
  { to: "/stats", label: "Stats" },
];

export default function Navbar() {
  return (
    <nav className="bg-gray-900 text-white shadow-lg">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center h-14 gap-8">
          <div className="flex items-center gap-2 shrink-0">
            <span className="text-blue-400 font-bold text-lg">Semiconductor Defect Inspection</span>
            <span className="text-xs text-gray-400 bg-gray-700 px-1.5 py-0.5 rounded">PoC</span>
          </div>

          <div className="flex gap-1">
            {NAV_ITEMS.map(({ to, label }) => (
              <NavLink
                key={to}
                to={to}
                end={to === "/"}
                className={({ isActive }) =>
                  `px-3 py-1.5 rounded text-sm font-medium transition-colors ${
                    isActive
                      ? "bg-blue-600 text-white"
                      : "text-gray-300 hover:bg-gray-700 hover:text-white"
                  }`
                }
              >
                {label}
              </NavLink>
            ))}
          </div>
        </div>
      </div>
    </nav>
  );
}
