import type { MetadataRoute } from 'next';
import { SITE_URL } from '@/lib/content';

const PATHS = ['/', '/services', '/approach', '/team', '/contact', '/demo', '/legal', '/legal/privacy'];

export default function sitemap(): MetadataRoute.Sitemap {
  return PATHS.map((path) => ({ url: SITE_URL + (path === '/' ? '' : path) }));
}
