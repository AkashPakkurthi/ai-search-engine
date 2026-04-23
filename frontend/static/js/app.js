// Global app utilities

document.addEventListener('DOMContentLoaded', () => {
    // Highlight active nav link
    const currentPath = window.location.pathname;
    document.querySelectorAll('.nav-link').forEach(link => {
        const href = link.getAttribute('href');
        if (currentPath === href || (href !== '/' && currentPath.startsWith(href))) {
            link.style.color = '#a29bfe';
        }
    });
});
