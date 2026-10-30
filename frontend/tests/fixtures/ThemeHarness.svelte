<script lang="ts">
	import 'bulma/css/bulma.min.css';
	import '../../src/app.css';
	import Footer from '../../src/lib/components/Footer.svelte';
	import RoleTag from '../../src/lib/components/RoleTag.svelte';
	import SubjectTag from '../../src/lib/components/SubjectTag.svelte';
	import TagSelector from '../../src/lib/components/TagSelector.svelte';
	import VisualPicker from '../../src/lib/components/VisualPicker.svelte';
	import FormattedText from '../../src/lib/components/lessons/FormattedText.svelte';
	import { roleOptions } from '../../src/lib/roles';
	import StatisticChart from '../../src/lib/components/statistics/StatisticChart.svelte';
	import { chartPalette } from '../../src/lib/statistics';
	import { colorForeground } from '../../src/lib/lessons';
	let selected = $state<string[]>(['teacher']);
	let icon = $state('physics');
	const colors = [
		'#000000',
		'#ffffff',
		'#ffff00',
		'#777777',
		'#ff0000',
		'#00ff00',
		'#0000ff',
		'#244bc1'
	];
</script>

<main class="container p-4">
	<section class="workspace-panel">
		<h1 class="title">Une plateforme pour apprendre</h1>
		<p class="muted">Texte secondaire lisible dans les deux thèmes.</p>
		<span class="tag is-light">Votre cours</span>
		<span class="tag is-light">Éditeur</span>
		{#each ['user', 'teacher', 'kholleur', 'admin'] as role (role)}<RoleTag {role} />{/each}
		<div class="my-4"><TagSelector options={roleOptions} bind:selected legend="Rôles" /></div>
		{#each colors as color (color)}
			<div class="mb-2">
				<SubjectTag subject={{ name: `Matière ${color}`, icon: 'science', color }} /><FormattedText
					text={`Texte ==${color}==`}
					{color}
				/>
			</div>
		{/each}
		<VisualPicker
			label="Icônes"
			bind:value={icon}
			choices={colors.map((color, index) => ({
				value: String(index),
				label: color,
				icon: 'science',
				color
			}))}
		/>
		<div class="field">
			<label class="label" for="example">Exemple de formulaire</label><input
				class="input"
				id="example"
				placeholder="Votre réponse"
			/>
		</div>
		<div class="select">
			<select aria-label="Exemple de liste"><option>Une matière</option></select>
		</div>
		<button class="button is-primary" type="button">Enregistrer</button>
		<button class="button is-light" type="button">Annuler</button>
		<button class="icon-button" type="button" aria-label="Exemple de bouton icône">+</button>
		<button class="button is-primary is-light" type="button">Générer de nouveaux liens</button>
		<button class="button is-text" type="button">Action discrète</button>
		<button class="button is-warning" type="button">Action sensible</button>
		<button
			class="button is-danger is-light"
			type="button"
			onclick={() => window.confirm('Révoquer ?')}>Révoquer les abonnements</button
		>
		<div class="promotion-grid">
			{#each ['#244bc1', '#ffffff', '#ffff00', '#777777'] as color (color)}
				<button
					class="promotion-card subject-card"
					style:--promotion-color={color}
					style:--promotion-ink={colorForeground(color)}
				>
					<span class="promotion-card-top"
						><span class="card-emblem" aria-hidden="true">M</span><span class="promotion-year"
							><span class="promotion-swatch" aria-hidden="true"></span>2026</span
						></span
					>
					<strong>Matière {color}</strong><span class="muted">Promotion {color}</span>
				</button>
			{/each}
		</div>
		<button
			class="button is-danger"
			type="button"
			onclick={() => window.confirm('Confirmer cette action ?')}>Action destructive</button
		>
		{#each ['success', 'warning', 'danger', 'info'] as status (status)}<p
				class="notification is-light is-{status} mt-3"
			>
				Message {status}
			</p>{/each}
		<p class="account-status">Actif</p>
		<p class="account-status pending">En attente</p>
		<table class="table is-fullwidth">
			<thead><tr><th>Matière</th><th>État</th></tr></thead><tbody
				><tr><td>Physique</td><td>Disponible</td></tr></tbody
			>
		</table>
		<StatisticChart
			title="Activité"
			labels={['Lundi', 'Mardi']}
			series={chartPalette.map((color, index) => ({
				key: String(index),
				label: `Série ${index + 1}`,
				color,
				values: [index + 1, index + 2]
			}))}
		/>
	</section>
</main>
<Footer establishmentName="Sophikron" />
