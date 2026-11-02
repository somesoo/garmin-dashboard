// Wariant alternatywny: pm2 zamiast systemd.
// Sens ma tylko wtedy, gdy na serwerze juz trzymasz inne procesy pod pm2 i
// chcesz miec wszystko w jednym "pm2 list". W przeciwnym razie uzyj
// deploy/garmin-dashboard.service (deploy/install.sh robi to sam).
//
//   pm2 start deploy/ecosystem.config.js
//   pm2 save && pm2 startup    # <- bez tego nie wstanie po reboocie
//   pm2 logs garmin-dashboard
//
// Jeden proces: serve.py = Streamlit (8501) + API dla telefonow (8502) + timer
// pobierania z Garmina dla kazdej osoby (GARMIN_AUTO_FETCH_H) - osobny cron ETL
// nie jest potrzebny.
module.exports = {
  apps: [
    {
      name: "garmin-dashboard",
      cwd: "/opt/garmin-dashboard",
      script: "/opt/garmin-dashboard/.venv/bin/python",
      args: [
        "serve.py",
        "--server.address", "127.0.0.1",
        "--server.port", "8501",
        "--server.headless", "true",
      ],
      interpreter: "none",        // script to juz plik wykonywalny, nie plik .js
      autorestart: true,
      max_restarts: 0,            // 0 = bez limitu, proces ma zyc
      restart_delay: 5000,
      max_memory_restart: "900M", // ratunek, gdy Streamlit spuchnie przy duzych wykresach
      env: {
        HOME: "/home/garmin",
        GARMIN_TOKENSTORE: "/home/garmin/.garminconnect",
        GARMIN_AUTO_FETCH_H: "6",
        GARMIN_API_PORT: "8502",
        PYTHONUNBUFFERED: "1",
      },
    },
  ],
};
