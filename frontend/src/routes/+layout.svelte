<script lang="ts">
	import favicon from '#lib/assets/favicon.svg';
	import type { LayoutProps } from './$types';
	import { page } from '$app/state';
	import 'bulma/css/bulma.min.css';
	import '../app.css';
	import Header from '#lib/components/Header.svelte';
	import Footer from '#lib/components/Footer.svelte';

	let { children, data }: LayoutProps = $props();
	const calendarWorkspace = $derived(/^\/timetable\/(?:\d+|prof)\/?$/.test(page.url.pathname));
</script>

<svelte:head>
	<link rel="icon" href={favicon} />
</svelte:head>

<a class="skip-link" href="#main-content">Aller au contenu</a>
{#if !calendarWorkspace}<Header user={data.user} establishmentName={data.establishmentName} />{/if}
<main id="main-content" tabindex="-1">{@render children()}</main>
{#if !calendarWorkspace}<Footer
		establishmentName={data.establishmentName}
		themePreference={data.themePreference}
	/>{/if}
