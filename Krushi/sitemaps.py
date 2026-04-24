from django.contrib.sitemaps import Sitemap
from django.urls import reverse

class StaticViewSitemap(Sitemap):
    priority = 0.8
    changefreq = 'daily'

    def items(self):
        return [
            'home', 'shop', 'about', 'contact', 'disease', 
            'soil_analysis', 'crop_planning', 'govsites', 
            'rating', 'privacy_policy', 'terms_conditions', 'disclaimer'
        ]

    def location(self, item):
        return reverse(item)
