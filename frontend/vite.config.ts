import adapter from '@sveltejs/adapter-node';
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

export default defineConfig({
	plugins: [
		sveltekit({
			adapter: adapter(),
			paths: { origin: process.env.ORIGIN || 'http://localhost:3000' }
		})
	],
	server: {
		watch: {
			usePolling: true,
			interval: 1000
		}
	}
});
