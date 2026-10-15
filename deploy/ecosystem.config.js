// Wariant alternatywny: pm2 zamiast systemd.
// Sens ma tylko wtedy, gdy na serwerze juz trzymasz inne procesy pod pm2 i
// chcesz miec wszystko w jednym "pm2 list". W przeciwnym razie uzyj
// deploy/garmin-dashboard.service - systemd jest tu prostszy i nie wymaga
// Node.js tylko po to, zeby pilnowac procesu Pythona.
//
//   pm2 start deploy/ecosystem.config.js
//   pm2 save && pm2 startup    # <- bez tego nie wstanie po reboocie
//   pm2 logs garmin-dashboard
module.exports = {
  apps: [
    {
      name: "garmin-dashboard",
      cwd: "/opt/garmin-dashboard",
      script: "/opt/garmin-dashboard/.venv/bin/python",
      args: [
        "-m", "streamlit", "run", "app.py",
        "--server.address", "127.0.0.1",
        "--server.port", "8501",
        "--server.headless", "true",
        "--browser.gatherUsageStats", "false",
      ],
      interpreter: "none",        // script to juz plik wykonywalny, nie plik .js
      autorestart: true,
      max_restarts: 0,            // 0 = bez limitu, proces ma zyc
      restart_delay: 5000,
      max_memory_restart: "900M", // ratunek, gdy Streamlit spuchnie przy duzych wykresach
      env: {
        HOME: "/home/garmin",
        GARMIN_TOKENSTORE: "/home/garmin/.garminconnect",
      },
    },
    {
      // ETL raz dziennie. pm2 ma wlasny cron, wiec nie potrzebujesz timera.
      name: "garmin-etl",
      cwd: "/opt/garmin-dashboard",
      script: "/opt/garmin-dashboard/.venv/bin/python",
      args: ["etl/run.py", "--days", "14"],
      interpreter: "none",
      autorestart: false,         // zadanie jednorazowe, nie serwer
      cron_restart: "30 7 * * *",
      env: {
        HOME: "/home/garmin",
        GARMIN_TOKENSTORE: "/home/garmin/.garminconnect",
      },
    },
  ],
};
