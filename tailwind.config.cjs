module.exports = {
    content: ['./app/templates/**/*.html', './app/static/js/app.js'],
    darkMode: 'class',
    theme: {
        extend: {
            fontFamily: {
                sans: ['"Be Vietnam Pro"', '"Plus Jakarta Sans"', 'sans-serif'],
                heading: ['"Plus Jakarta Sans"', '"Be Vietnam Pro"', 'sans-serif'],
                serif: ['"Lora"', '"Literata"', '"Merriweather"', 'serif'],
                mono: ['"JetBrains Mono"', 'monospace'],
            },
        },
    },
    plugins: [require('daisyui')],
    daisyui: { themes: ['dark'], logs: false },
};
