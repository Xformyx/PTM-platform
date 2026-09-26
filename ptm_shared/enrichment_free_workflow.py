"""One explicit primary-A run: raw matrices through a frozen, portable export.

Runs are immutable and recomputed. No result cache is relabelled with a new design.
This report is a deterministic evidence report, not the legacy LLM manuscript.
"""
import html
import json
from pathlib import Path
import shutil
from uuid import uuid4
import zipfile

import pandas as pd

from .enrichment_free_profile import PROFILE, annotation_snapshot, validate_profile
from .normalization_provenance import normalize_supplied_matrices
from .report_compatible_quantification import quantify_forms, read_fasta
from .report_compatible_kinase import frozen_edges, score_footprints
from .report_compatible_extensions import extend_and_export, file_digest, EXPORT_VERSION


def finalize_bundle(directory):
    directory = Path(directory)
    provenance = json.loads((directory / 'provenance.json').read_text())
    files = {str(p.relative_to(directory)): {
        'bytes':p.stat().st_size, 'sha256':file_digest(p),
        **{key:provenance[key] for key in ('order_id','run_id','provenance_id')}}
        for p in sorted(directory.rglob('*'))
        if p.is_file() and p.name != 'manifest.json' and '__pycache__' not in p.parts}
    (directory / 'manifest.json').write_text(json.dumps({'schema_version':EXPORT_VERSION,'files':files},indent=2))
    archive = directory.with_suffix('.zip')
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as out:
        for name in [*files, 'manifest.json']:
            out.write(directory / name, name)
    return archive


def run_primary_analysis(order_id, config, output_dir, checkpoint=lambda:None, progress=lambda message:None):
    context = config['experimental_context']
    samples = validate_profile(context, config['condition_map'], config['ptm_mode'],
                               config['species_tax_id'], config.get('analysis_options'))
    frozen = config['frozen_annotation']
    registered = annotation_snapshot(Path(frozen['reference_dir']).parent, frozen['sha256'])
    inputs = {key:Path(config[name]) for key,name in
              [('PR','pr_matrix_path'),('PG','pg_matrix_path'),('FASTA','fasta_path')]}
    inputs['snapshot'] = Path(registered['snapshot_path'])
    run_id = f"g{int(config.get('run_generation') or 0)}-{uuid4().hex}"
    root = Path(output_dir)
    directory = root / 'enrichment_free_runs' / run_id
    progress('Quantifying charge-collapsed forms with paired PG adjustment')
    pr, pg, normalization = normalize_supplied_matrices(pd.read_csv(inputs['PR'],sep='\t'),
        pd.read_csv(inputs['PG'],sep='\t'), [s['original_column'] for s in samples], context['normalization_policy'])
    analysis = quantify_forms(pr,pg,read_fasta(inputs['FASTA']),samples)
    checkpoint()
    progress('Scoring frozen annotation and explicit U/P comparison modes')
    mappings, edges = frozen_edges(analysis,pd.read_csv(inputs['snapshot'],sep='\t'))
    kinase = score_footprints(analysis,edges)
    checkpoint()
    run_context = {'order_id':order_id,'order_code':config['order_code'],'run_id':run_id,
        'run_generation':config.get('run_generation'),'sample_manifest':context['sample_manifest'],
        'analysis_profile':PROFILE,'acquisition_metadata':context.get('acquisition_metadata',{})}
    progress('Exporting paired parent, emergence, late protein layer and evidence report')
    exported = extend_and_export(analysis,mappings,edges,kinase,directory,inputs,
        reference_dir=registered['reference_dir'],run_context=run_context,normalization=normalization,make_archive=False)
    provenance = exported['provenance']
    primary = analysis['comparisons'].loc[analysis['comparisons'].included].copy()
    primary['estimator_version'] = provenance['estimator_versions']['quantification']
    primary['provenance_id'] = provenance['provenance_id']
    primary.to_csv(directory / 'primary_A_input.csv',index=False)
    report = build_evidence_report(analysis,kinase,provenance)
    (directory / 'evidence_report.md').write_text(report)
    (directory / 'evidence_report.html').write_text('<!doctype html><html lang="en"><meta charset="utf-8">'
        '<title>Primary A evidence report</title><style>body{max-width:1000px;margin:3rem auto;padding:0 2rem;font:16px/1.6 system-ui}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style>'
        '<body><pre>'+html.escape(report)+'</pre></body></html>')
    contract = {'schema_version':'primary_A_input_contract.v2','primary_input':'primary_A_input.csv',
        'primary_value':'A','primary_eligibility':'included == true','explanatory_channels':['U_joint','P_joint','U_all','P_all'],
        'legacy_precursor_estimator_used':False,'profile':PROFILE,'provenance_id':provenance['provenance_id'],
        'result_cache_policy':'recompute_each_run; previous_run_provenance_is_immutable'}
    (directory / 'primary_input_contract.json').write_text(json.dumps(contract,indent=2))
    dictionary = json.loads((directory / 'data_dictionary.json').read_text())
    dictionary['tables']['primary_A_input.csv'] = {**dictionary['tables']['comparisons.csv'],
        'meaning':'Eligible primary A analysis input; U/P are explanatory QC channels only.',
        'columns':list(primary.columns)}
    (directory / 'data_dictionary.json').write_text(json.dumps(dictionary,indent=2))
    archive = finalize_bundle(directory)
    checkpoint()
    published_archive = root / f'enrichment_free_{run_id}.zip'
    shutil.copyfile(archive,published_archive)
    artifacts = {name:{'path':str(path.relative_to(root)), 'sha256':file_digest(path)} for name,path in {
        'astra':published_archive,'report':directory/'evidence_report.html',
        'report_markdown':directory/'evidence_report.md','primary_input':directory/'primary_A_input.csv',
        'provenance':directory/'provenance.json'}.items()}
    result = {'schema_version':'enrichment_free_run.v2','run_id':run_id,'provenance':provenance,
        'artifacts':artifacts,'primary_input_contract':contract,
        'counts':{'forms':len(analysis['summary']),'primary_comparisons':len(primary),
                  'kinase_profiles_v1':len(kinase['profiles'])},
        'analysis_readiness':json.loads((directory/'analysis_readiness.json').read_text()),
        'primary_profiles':json.loads(kinase['profiles'].loc[kinase['profiles']['mode'].eq('primary_A')].to_json(orient='records'))}
    (directory/'platform_run.json').write_text(json.dumps(result,indent=2))
    # Atomic pointer publication occurs only after all calculation/export succeeds.
    checkpoint()
    pending = root / f'.enrichment_free_{run_id}.json'
    pending.write_text(json.dumps(result,indent=2))
    pending.replace(root/'enrichment_free_current.json')
    return result


def build_evidence_report(analysis, kinase, provenance):
    profiles = kinase['profiles']
    families = profiles.loc[profiles['mode'].eq('primary_A') & profiles.entity.isin(['AKT_family','ERK1_2_family','S6K_family'])]
    lines = ['# Enrichment-free phosphorylation evidence report',
        f"Order: {provenance['order_code']} | Run: {provenance['run_id']}",
        f"Provenance: {provenance['provenance_id']}",
        f"Primary input: A, estimator {provenance['estimator_versions']['quantification']}.",
        f"Eligible form × time comparisons: {int(analysis['comparisons'].included.sum())}.",
        'A is the change in mean log2(PTM / PG) on identical injections, with at least two joint observations per condition. U/P remain QC channels.',
        'Strict alternative parent default: paired per-peptide log ratios v2, at least two joint observations per condition and two independent sequences. v1 and complete-mask sensitivities remain separate.',
        '## Exploratory frozen kinase footprints',
        '| Entity | Minutes | Gene-balanced score | Coverage / pattern |','|---|---:|---:|---|']
    for row in families.itertuples():
        lines.append(f'| {row.entity} | {row.time_min:g} | {row.gene_balanced_mean:.4f} | {row.descriptive_pattern} |')
    lines.extend(['## Interpretation limits',
        'These are descriptive substrate footprints, not causal kinase activity validation. Strict attribution is no-call because localization probabilities are unavailable. Rat orthology translation and S6K source-caution sensitivity must accompany interpretation.',
        'Technical injections do not establish biological replication; no biological p/q is generated. Baseline-undetected forms have no invented baseline fold-change. Emergent evidence retains each form’s post-reference time and must not be averaged as baseline evidence.',
        'Late protein changes are same-experiment descriptive consistency. Held-out genes were fixed for reanalysis after reviewing the original report, not prospectively preregistered.',
        '## Run configuration',json.dumps(provenance,indent=2,ensure_ascii=False)])
    return '\n\n'.join(lines)+'\n'


def recorded_run(output_dir):
    root = Path(output_dir).resolve()
    record = json.loads((root/'enrichment_free_current.json').read_text())
    for artifact in record['artifacts'].values():
        path = (root/artifact['path']).resolve()
        if not path.is_relative_to(root) or not path.is_file() or file_digest(path) != artifact['sha256']:
            raise ValueError('Evidence artifact integrity failure')
    return record
