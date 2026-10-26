<script lang="ts">
	import favicon from '#lib/assets/favicon.svg';
	import type { LayoutProps } from './$types';
	import 'bulma/css/bulma.min.css';
	import '../app.css';
	import Header from '#lib/components/Header.svelte';
	import Footer from '#lib/components/Footer.svelte';

	let { children, data }: LayoutProps = $props();
</script>

<svelte:head>
	<link rel="icon" href={favicon} />
</svelte:head>

<a class="skip-link" href="#main-content">Aller au contenu</a>
<Header user={data.user} establishmentName={data.establishmentName} />
<main id="main-content" tabindex="-1">{@render children()}</main>
<Footer establishmentName={data.establishmentName} themePreference={data.themePreference} />
