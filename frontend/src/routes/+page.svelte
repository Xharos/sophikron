<script lang="ts">
	import { resolve } from '$app/paths';
	import type { PageProps } from './$types';
	let { data }: PageProps = $props();
</script>

<svelte:head>
	<title>{data.establishmentName} — Apprendre, ensemble</title>
	<meta
		name="description"
		content={`${data.establishmentName}, la plateforme pédagogique libre pour les enseignants et leurs élèves.`}
	/>
	<link rel="canonical" href={`${data.siteOrigin}/`} />
	<meta property="og:title" content={`${data.establishmentName} — Apprendre, ensemble`} />
	<meta
		property="og:description"
		content="Un espace commun pour les enseignants et leurs élèves."
	/>
	<meta property="og:type" content="website" />
	<meta property="og:url" content={`${data.siteOrigin}/`} />
</svelte:head>

<section class="section home-hero container">
	<div class="hero-copy">
		<p class="eyebrow"><span class="status-dot"></span> La pédagogie, en commun</p>
		<h1 class="title display-title">
			Un espace pour<br />apprendre<span class="accent">.</span><br /><span class="muted"
				>Ensemble.</span
			>
		</h1>
		<p class="hero-description">
			Relier les enseignants et les élèves. Donner à chacun une place pour progresser. Bienvenue sur
			{data.establishmentName}.
		</p>
		<div class="buttons mt-5">
			<a class="button is-primary is-medium" href={resolve('/lessons')}
				>Accéder à mon espace <span aria-hidden="true">↗</span></a
			>
		</div>
	</div>
	<div class="hero-art" aria-hidden="true">
		<div class="art-grid"></div>
		<div class="art-circle"></div>
		<span class="art-label">LE SAVOIR SE PARTAGE</span>
		<div class="art-card">
			<span class="art-number">01 /</span><span class="art-word"
				>Enseigner.<br />Apprendre.<br /><strong>Grandir.</strong></span
			><span class="art-arrow">↗</span>
		</div>
		<div class="art-note">
			<span class="status-dot"></span> Un projet libre. Un horizon commun.
		</div>
	</div>
</section>
<section class="section home-principles container" aria-label="Nos principes">
	<div>
		<span class="principle-number">01</span>
		<h2>Clair par nature.</h2>
		<p>Une place pour l’essentiel : l’enseignement et l’apprentissage.</p>
	</div>
	<div>
		<span class="principle-number">02</span>
		<h2>Pensé pour chacun.</h2>
		<p>Un espace commun aux enseignants et à leurs élèves.</p>
	</div>
	<div>
		<span class="principle-number">03</span>
		<h2>Libre de construire.</h2>
		<p>Un logiciel libre, conçu pour évoluer avec les usages.</p>
	</div>
</section>
