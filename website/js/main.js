/* ====================================================================
   LYRA AI PLATFORM — Main JS
   lyraauth.com
   ==================================================================== */

// ── Nav scroll shadow ──
const nav = document.getElementById('nav');
if (nav) {
  window.addEventListener('scroll', () => {
    nav.style.boxShadow = window.scrollY > 20
      ? '0 4px 32px rgba(0,0,0,0.4)'
      : 'none';
  }, { passive: true });
}

// ── Smooth anchor scroll ──
document.querySelectorAll('a[href^="#"]').forEach(link => {
  link.addEventListener('click', e => {
    const id = link.getAttribute('href').slice(1);
    const el = document.getElementById(id);
    if (el) {
      e.preventDefault();
      el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  });
});

// ── Intersection observer fade-in for cards ──
const observerOptions = { threshold: 0.1, rootMargin: '0px 0px -40px 0px' };
const observer = new IntersectionObserver((entries) => {
  entries.forEach(entry => {
    if (entry.isIntersecting) {
      entry.target.style.opacity = '1';
      entry.target.style.transform = 'translateY(0)';
      observer.unobserve(entry.target);
    }
  });
}, observerOptions);

document.querySelectorAll('.card, .product-card, .price-card, .step').forEach(el => {
  el.style.opacity = '0';
  el.style.transform = 'translateY(24px)';
  el.style.transition = 'opacity 0.5s ease, transform 0.5s ease';
  observer.observe(el);
});
