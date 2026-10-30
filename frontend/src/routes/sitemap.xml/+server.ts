import type { RequestHandler } from './$types';

export const GET: RequestHandler = () => {
	const origin = process.env.ORIGIN || 'http://localhost:3000';
	const escaped = origin.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('"', '&quot;');
	return new Response(
		`<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>${escaped}/</loc></url></urlset>`,
		{ headers: { 'Content-Type': 'application/xml; charset=utf-8' } }
	);
};
