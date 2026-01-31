/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        'bg-page': '#f5f5f5',
        'bg-card': '#ffffff',
        'text-primary': '#333333',
        'text-secondary': '#666666',
        'text-tertiary': '#999999',
        'border': '#eeeeee',
        'green-healthy': '#28a745',
        'red-critical': '#d32f2f',
        'yellow-warning': '#ffc107',
        'orange-alert': '#ff9800',
      },
      boxShadow: {
        'card': '0 2px 4px rgba(0,0,0,0.1)',
      },
      borderRadius: {
        'card': '8px',
      }
    },
  },
  plugins: [],
}
