<script lang="ts">
	import { onMount } from 'svelte';
	import { SvelteURLSearchParams } from 'svelte/reactivity';
	import { resolve } from '$app/paths';
	import {
		byteLabel,
		breakdownSeries,
		chartPalette,
		timeLabels,
		type ChartSeries,
		type Statistics,
		type StatisticsPeriod
	} from '#lib/statistics';
	import { loginDestination } from '#lib/loginRedirect';
	import StatCard from './StatCard.svelte';
	import StatisticChart from './StatisticChart.svelte';
	import Icon from '../Icon.svelte';
	import Modal from '../Modal.svelte';
	import { page } from '$app/state';
	import { hasPermission } from '#lib/access';
	import ApiMonitoringPanel from './ApiMonitoringPanel.svelte';
	let { lessonId, onrefresh = () => {} }: { lessonId?: number; onrefresh?: () => void } = $props();
	let period = $state<StatisticsPeriod>('week');
	let statistics = $state<Statistics | null>(null);
	let loading = $state(true);
	let ready = $state(false);
	let revision = $state(0);
	let message = $state('');
	let accountsView = $state<'status' | 'roles'>('status');
	let calendarOpen = $state(false);
	let catalogue = $state<'promotions' | 'subjects'>('promotions');
	onMount(() => {
		ready = true;
	});
	$effect(() => {
		const selectedPeriod = period;
		const id = lessonId;
		void revision;
		if (!ready) return;
		const controller = new AbortController();
		void (async () => {
			loading = true;
			message = '';
			try {
				const query = new SvelteURLSearchParams({ period: selectedPeriod });
				if (id !== undefined) query.set('lessonId', String(id));
				const response = await fetch(`/statistics?${query}`, {
					signal: controller.signal,
					cache: 'no-store'
				});
				if (response.status === 401)
					window.location.assign(
						loginDestination(window.location.pathname + window.location.search)
					);
				const body = await response.json();
				if (!response.ok) throw new Error(body.message || 'Statistiques indisponibles.');
				if (!controller.signal.aborted) statistics = body as Statistics;
			} catch (cause) {
				if (!controller.signal.aborted) {
					message = (cause as Error).message;
					statistics = null;
				}
			} finally {
				if (!controller.signal.aborted) loading = false;
			}
		})();
		return () => controller.abort();
	});
	const labels = $derived(statistics ? timeLabels(statistics.timestamps, statistics.period) : []);
	const details = $derived(
		statistics ? timeLabels(statistics.timestamps, statistics.period, true) : []
	);
	const accountTotal = $derived(
		statistics?.accounts.reduce((sum, item) => sum + item.value, 0) || 0
	);
	function series(keys: [string, string][]): ChartSeries[] {
		return keys.map(([key, label], index) => ({
			key,
			label,
			values: statistics?.series[key] || [],
			color: chartPalette[index]
		}));
	}
	const count = (value: number): string => value.toLocaleString('fr-FR');
</script>

<div class="statistics-panel" aria-busy={loading}>
	<div class="statistics-toolbar">
		<div>
			<p class="mini-label">
				{lessonId
					? 'Activité du cours'
					: statistics?.scope === 'author'
						? 'Mes cours créés'
						: 'Pilotage de la plateforme'}
			</p>
			<p class="muted text-small">
				{period === 'day'
					? 'Aujourd’hui, heure par heure'
					: period === 'week'
						? 'Les 7 derniers jours, aujourd’hui inclus'
						: 'Les 30 derniers jours, aujourd’hui inclus'} · heure de Paris
			</p>
		</div>
		<div class="statistics-controls">
			<div class="stat-switch" role="group" aria-label="Période des statistiques">
				{#each [['day', 'Jour'], ['week', 'Semaine'], ['month', 'Mois']] as [key, label] (key)}<button
						aria-pressed={period === key}
						class:active={period === key}
						onclick={() => (period = key as StatisticsPeriod)}>{label}</button
					>{/each}
			</div>
			<button
				class="button is-light is-small"
				disabled={loading}
				onclick={() => {
					revision += 1;
					onrefresh();
				}}><Icon name="restore" size={14} />Actualiser</button
			>
		</div>
	</div>
	{#if message}<p class="notification is-danger is-light" role="alert">{message}</p>{/if}
	{#if loading}<p class="statistics-loading" role="status">Chargement des statistiques…</p>{/if}
	{#if statistics && !loading}
		<div class="statistics-grid">
			{#if statistics.scope === 'admin'}
				<StatCard
					title="Les comptes"
					subtitle="État actuel de tous les comptes permanents"
					value={count(accountTotal)}
					caption={`compte${accountTotal === 1 ? '' : 's'} au total`}
				>
					<div class="stat-switch" role="group" aria-label="Répartition des comptes">
						<button
							class:active={accountsView === 'status'}
							aria-pressed={accountsView === 'status'}
							onclick={() => (accountsView = 'status')}>États</button
						><button
							class:active={accountsView === 'roles'}
							aria-pressed={accountsView === 'roles'}
							onclick={() => (accountsView = 'roles')}>Rôles</button
						>
					</div>
					{#if accountsView === 'status'}<StatisticChart
							title="État des comptes"
							kind="donut"
							series={breakdownSeries(statistics.accounts)}
							center="comptes visibles"
						/>{:else}<StatisticChart
							title="Rôles des comptes"
							kind="bars"
							labels={statistics.roles.map((item) => item.label)}
							series={[
								{
									key: 'roles',
									label: 'Comptes par rôle',
									values: statistics.roles.map((item) => item.value),
									color: chartPalette[0]
								}
							]}
						/>
						<p class="stat-note">
							Les rôles se cumulent : un compte peut apparaître dans plusieurs barres.
						</p>{/if}
					<a class="stat-link" href={resolve('/dashboard?tab=accounts')}
						>Gérer les comptes <Icon name="arrow" size={13} /></a
					>
				</StatCard>
				<StatCard
					title="Abonnements calendrier"
					subtitle="Comptes actuellement éligibles · période sélectionnée"
					value={`${count(statistics.calendar_recent_users ?? 0)}/${count(statistics.calendar_eligible_users ?? 0)}`}
					caption="consultés sur la période / comptes actuellement éligibles"
				>
					<StatisticChart
						title="Utilisation des abonnements"
						kind="donut"
						series={breakdownSeries(statistics.calendar_subscriptions ?? [])}
						center="comptes éligibles"
					/>
					<button class="button is-light" onclick={() => (calendarOpen = true)}
						>Voir l’utilisation</button
					>
					<p class="stat-note">
						{count(statistics.calendar_requests_total ?? 0)} requêtes ICS autorisées traitées avec succès
						depuis le début du suivi.
					</p>
				</StatCard>
				<StatCard
					title="Connexions"
					subtitle="Comptes uniques, réussites et tentatives traitées"
					value={count(statistics.totals.unique_logins)}
					caption={`compte${statistics.totals.unique_logins === 1 ? '' : 's'} unique${statistics.totals.unique_logins === 1 ? '' : 's'} sur la période`}
				>
					<StatisticChart
						title="Évolution des connexions"
						{labels}
						{details}
						series={series([
							['unique_logins', 'Comptes uniques'],
							['logins', 'Réussies'],
							['attempts', 'Tentatives']
						])}
					/>
					<p class="stat-note">
						{count(statistics.totals.failures)} échec{statistics.totals.failures === 1 ? '' : 's'} · {count(
							statistics.totals.limited
						)} demande{statistics.totals.limited === 1 ? '' : 's'} limitée{statistics.totals
							.limited === 1
							? ''
							: 's'}. Les tentatives incluent les réussites, échecs et limitations.
					</p>
					{#if statistics.attempts_since}<p class="stat-note">
							Échecs et limitations suivis depuis le {new Date(
								statistics.attempts_since
							).toLocaleString('fr-FR', { timeZone: 'Europe/Paris' })}. Les périodes antérieures
							sont incomplètes.
						</p>{/if}
				</StatCard>
			{/if}
			<StatCard
				title="Téléchargements"
				subtitle="Transferts complets côté serveur"
				value={count(statistics.totals.downloads)}
				caption={`téléchargement${statistics.totals.downloads === 1 ? '' : 's'} sur la période`}
			>
				<StatisticChart
					title="Évolution des téléchargements"
					{labels}
					{details}
					series={series([
						['downloads', 'Téléchargements'],
						['downloaders', 'Comptes uniques']
					])}
				/>
				<p class="stat-note">
					{count(statistics.totals.downloaders)} compte{statistics.totals.downloaders === 1
						? ''
						: 's'} unique{statistics.totals.downloaders === 1 ? '' : 's'} sur la période entière. Les
					valeurs uniques de chaque point ne s’additionnent pas.
				</p>
				<p class="stat-note">
					Le suivi commence à sa mise en place. Un transfert complet ne garantit pas
					l’enregistrement sur l’appareil.
				</p>
			</StatCard>
			<StatCard
				title={lessonId ? 'Stockage du cours' : 'Stockage documentaire'}
				subtitle="Documents actuellement publiés"
				value={byteLabel(statistics.storage.bytes)}
				caption={`${count(statistics.storage.files)} fichier${statistics.storage.files === 1 ? '' : 's'}`}
			>
				{#if statistics.storage.quota_bytes}<div>
						<progress
							class="progress is-link is-small mb-2"
							value={statistics.storage.bytes + statistics.storage.reserved_bytes}
							max={statistics.storage.quota_bytes}
							aria-label="Quota documentaire utilisé"
						></progress>
						<p class="stat-note">
							{byteLabel(statistics.storage.bytes)} sur {byteLabel(statistics.storage.quota_bytes)} ·
							{byteLabel(statistics.storage.reserved_bytes)} réservé{statistics.storage
								.reserved_bytes === 1
								? ''
								: 's'} pour les dépôts en cours.
						</p>
					</div>{/if}
				<StatisticChart
					title="Volume des documents par format"
					kind="donut"
					series={breakdownSeries(statistics.storage.formats)}
					format={byteLabel}
					center="volume visible"
				/>
				{#if statistics.scope === 'admin'}<div class="storage-facts">
						<span
							>Objets sur disque <b
								>{statistics.storage.physical_bytes === null
									? 'Indisponible'
									: byteLabel(statistics.storage.physical_bytes)}</b
							></span
						><span
							>Fichiers temporaires <b
								>{statistics.storage.temporary_bytes === null
									? 'Indisponible'
									: byteLabel(statistics.storage.temporary_bytes)}</b
							></span
						><span>Suppressions en attente <b>{statistics.storage.pending_deletions}</b></span>
					</div>{/if}
			</StatCard>
			<StatCard
				title={lessonId ? 'Documents les plus téléchargés' : 'Cours les plus téléchargés'}
				subtitle="Les cinq premiers sur la période sélectionnée"
			>
				<StatisticChart
					title="Ressources populaires"
					kind="bars"
					labels={statistics.popular.map((item) => item.label)}
					series={[
						{
							key: 'popular',
							label: 'Téléchargements',
							values: statistics.popular.map((item) => item.value),
							color: chartPalette[1]
						}
					]}
				/>
				{#if !lessonId}<ul class="stat-resource-links">
						{#each statistics.popular as item (item.id)}<li>
								{#if item.id !== null}<a href={resolve('/lessons/[id]', { id: String(item.id) })}
										>{item.label}</a
									>{:else}{item.label}{/if}
							</li>{/each}
					</ul>{/if}
			</StatCard>
			{#if statistics.scope === 'admin'}
				<StatCard
					title="Promotions et matières"
					subtitle="Effectifs et cours actuellement référencés"
				>
					<div class="stat-switch" role="group" aria-label="Catalogue de l’établissement">
						<button
							class:active={catalogue === 'promotions'}
							aria-pressed={catalogue === 'promotions'}
							onclick={() => (catalogue = 'promotions')}>Promotions</button
						><button
							class:active={catalogue === 'subjects'}
							aria-pressed={catalogue === 'subjects'}
							onclick={() => (catalogue = 'subjects')}>Matières</button
						>
					</div>
					{#if catalogue === 'promotions'}<StatisticChart
							title="Effectifs des promotions actives"
							kind="stacked"
							labels={statistics.promotions.map((item) => item.label)}
							series={[
								{
									key: 'pupils',
									label: 'Élèves',
									values: statistics.promotions.map((item) => item.value),
									color: chartPalette[0]
								},
								{
									key: 'staff',
									label: 'Enseignants et khôlleurs',
									values: statistics.promotion_staff.map((item) => item.value),
									color: chartPalette[1]
								}
							]}
						/><a class="stat-link" href={resolve('/dashboard?tab=promotions')}
							>Gérer les promotions <Icon name="arrow" size={13} /></a
						>{:else}<StatisticChart
							title="Cours par matière active"
							kind="bars"
							labels={statistics.subjects.map((item) => item.label)}
							series={[
								{
									key: 'subjects',
									label: 'Cours',
									values: statistics.subjects.map((item) => item.value),
									color: chartPalette[3]
								}
							]}
						/><a class="stat-link" href={resolve('/dashboard?tab=subjects')}
							>Gérer les matières <Icon name="arrow" size={13} /></a
						>{/if}
				</StatCard>
			{/if}
		</div>
		{#if statistics.scope === 'author'}<section class="workspace-panel author-course-list">
				<h3 class="title is-5">Mes cours créés</h3>
				<p class="stat-note">
					Cette vue inclut uniquement vos créations. Les statistiques des autres cours auxquels vous
					collaborez sont accessibles depuis leur page.
				</p>
				{#if !statistics.courses.length}<p class="muted">
						Vous n’avez pas encore créé de cours.
					</p>{:else}<ul>
						{#each statistics.courses as course (course.id)}<li>
								{#if course.id !== null}<a
										href={resolve('/lessons/[id]', { id: String(course.id) })}
										>{course.label}<Icon name="arrow" size={13} /></a
									>{:else}{course.label}{/if}
							</li>{/each}
					</ul>{/if}
			</section>{/if}
		<p class="statistics-updated">
			Actualisé le {new Date(statistics.generated_at).toLocaleString('fr-FR', {
				timeZone: 'Europe/Paris'
			})}
		</p>
	{/if}
	{#if lessonId === undefined && hasPermission(page.data.user, 'statistics.read')}
		<ApiMonitoringPanel {period} {revision} />
	{/if}
</div>

{#if calendarOpen && statistics?.scope === 'admin'}
	<Modal
		title="Utilisation des abonnements calendrier"
		description="Consultations sur la période parmi les comptes actuellement éligibles."
		onclose={() => (calendarOpen = false)}
	>
		<StatisticChart
			title="Utilisation des liens actuels"
			kind="donut"
			series={breakdownSeries(statistics.calendar_subscriptions ?? [])}
			center="comptes éligibles"
		/>
		<p class="mt-4">
			<strong>{count(statistics.calendar_recent_users ?? 0)}</strong> abonnement(s) consulté(s) sur la
			période sélectionnée.
		</p>
		<p class="help mt-3">
			Une consultation correspond à une récupération réussie du flux, même vide. Elle peut provenir
			d’une application, des serveurs de Google ou d’un téléchargement manuel ; elle ne prouve pas
			que le calendrier a été regardé.
		</p>
		<p class="help mt-2">
			Chaque compte éligible est compté une seule fois. La régénération conserve l’historique
			d’utilisation. Les requêtes sans calendrier autorisé ou avec un lien révoqué ne sont pas
			comptées.
		</p>
	</Modal>
{/if}

<style>
	.statistics-toolbar {
		display: flex;
		justify-content: space-between;
		gap: 1rem;
		flex-wrap: wrap;
		margin-bottom: 1.3rem;
		align-items: center;
	}
	.statistics-controls {
		display: flex;
		gap: 0.65rem;
		flex-wrap: wrap;
		align-items: center;
	}
	.statistics-grid {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 1.2rem;
		align-items: stretch;
	}
	.stat-switch {
		display: flex;
		gap: 0.15rem;
		padding: 0.2rem;
		background: var(--color-paper);
		border-radius: 0.55rem;
		width: fit-content;
		max-width: 100%;
		flex-wrap: wrap;
	}
	.stat-switch button {
		font: inherit;
		font-size: 0.73rem;
		border: 0;
		border-radius: 0.4rem;
		padding: 0.45rem 0.7rem;
		background: transparent;
		color: var(--color-muted);
		cursor: pointer;
	}
	.stat-switch button.active {
		color: var(--color-primary);
		background: var(--color-surface);
		box-shadow: 0 1px 4px #172b3612;
		font-weight: 650;
	}
	.stat-note {
		color: var(--color-muted);
		font-size: 0.72rem;
		line-height: 1.55;
	}
	.stat-link {
		display: flex;
		align-items: center;
		gap: 0.4rem;
		font-size: 0.8rem;
		margin-top: auto;
	}
	.storage-facts {
		display: flex;
		flex-direction: column;
		gap: 0.35rem;
		font-size: 0.72rem;
		color: var(--color-muted);
	}
	.storage-facts span {
		display: flex;
		justify-content: space-between;
		gap: 0.5rem;
	}
	.stat-resource-links {
		font-size: 0.73rem;
		list-style: none;
		display: flex;
		flex-direction: column;
		gap: 0.3rem;
	}
	.statistics-loading {
		background: var(--color-paper);
		border-radius: 0.6rem;
		padding: 1.5rem;
		color: var(--color-muted);
	}
	.statistics-updated {
		text-align: right;
		color: var(--color-muted);
		font-size: 0.7rem;
		margin: 1rem 0;
	}
	.author-course-list {
		padding: 1.4rem;
		margin-top: 1.2rem;
	}
	.author-course-list ul {
		list-style: none;
		margin-top: 1rem;
	}
	.author-course-list a {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 0.6rem 0;
		border-bottom: var(--border-thin);
	}
	@media (min-width: 1600px) {
		.statistics-grid {
			grid-template-columns: repeat(3, minmax(0, 1fr));
		}
	}
	@media (max-width: 760px) {
		.statistics-grid {
			grid-template-columns: minmax(0, 1fr);
		}
	}
</style>
