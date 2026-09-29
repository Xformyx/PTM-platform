"""Deterministic evidence plots with complete source rows and public selection rules."""
import numpy as np
import pandas as pd
from .generic_workflow import json_write


def figure_packet(tables,directory):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    matplotlib.rcParams['svg.hashsalt']='PTM-Astra-v4'
    output=directory/'figures';output.mkdir(exist_ok=True);legends=[]
    def save(name,key,draw,selection):
        frame=tables[key];frame.to_csv(output/(name+'_source.csv'),index=False)
        fig,ax=plt.subplots(figsize=(10,5));draw(ax,frame)
        ax.set_title(name.replace('_',' '));fig.tight_layout()
        fig.savefig(output/(name+'.svg'),metadata={'Date':None});plt.close(fig)
        legends.append({'figure_id':name,'source_table':key,'source_data':name+'_source.csv','selection':selection,
                        'missing':'omitted points or gray cells, never numeric zero','error_bars':'none; technical variation is not a biological CI','full_source_rows':len(frame)})
    def empty(ax):ax.text(.5,.5,'Not evaluable: see readiness and source data',ha='center',transform=ax.transAxes)
    def bars(ax,f):
        ax.barh(f.metric,f['count']);ax.set_xlabel('Count (row grain and denominator in source data)')
    save('coverage','evidence/coverage_funnel',bars,'all recorded coverage metrics')
    def qc(ax,f):
        groups=[(str(k),g.log2_SD.dropna().to_numpy()) for k,g in f.groupby('track',sort=True)]
        groups=[(k,v) for k,v in groups if len(v)]
        if groups:
            ax.boxplot([v for _,v in groups],showfliers=False)
            ax.set_xticks(range(1,len(groups)+1),[k for k,_ in groups])
        else:empty(ax)
        ax.set_ylabel('Within-condition log2 SD (measurement dispersion)')
    save('technical_dispersion','evidence/technical_dispersion',qc,'all finite rows; boxes show distribution of technical dispersion, not confidence intervals')
    def correction(ax,f):
        for name,g in f.loc[f.included].groupby('classification',sort=True):
            ax.scatter(g.U_joint,g.A,s=8,alpha=.5,label=name)
        limits=ax.get_xlim();ax.plot(limits,limits,color='black',linestyle='--',linewidth=.6)
        ax.set_xlabel('U_joint (log2 PTM contrast)');ax.set_ylabel('A (log2 parent-adjusted contrast)')
        if len(f):ax.legend(fontsize=6)
    save('parent_correction','evidence/parent_adjustment_impact',correction,'all eligible comparisons; categories are operational effects, not kinase activation')
    def upa(ax,f):
        f=f.loc[f.included].assign(size=lambda x:x.P_joint.abs()).sort_values(['size','form_id','contrast_id'],ascending=[False,True,True]).head(12)
        if len(f):
            x=np.arange(len(f))
            for i,(key,color) in enumerate([('U_joint','#4677af'),('P_joint','#a28a47'),('A','#a54848')]):ax.bar(x+(i-1)*.25,f[key],width=.25,label=key,color=color)
            ax.set_xticks(x,[a+'/'+b for a,b in zip(f.form_id,f.contrast_id)],rotation=50,ha='right',fontsize=6);ax.legend()
        else:empty(ax)
        ax.set_ylabel('Log2 contrast, identical joint masks')
    save('U_P_A_examples','evidence/parent_adjustment_impact',upa,'12 largest absolute P_joint, ties form/contrast ID; all opposing rows retained in source')
    def curves(ax,f,entity,value,track=None):
        if track is not None:f=f.loc[f.track.eq(track)]
        keys=[entity,'arm_id','reference_condition_id']
        for key,g in list(f.groupby(keys,sort=True))[:12]:
            g=g.sort_values(['time_min','contrast_id']);ax.plot(g.time_min,g[value],marker='o',markersize=3,label='/'.join(map(str,key)))
        ax.set_xlabel('Actual target time (minutes)');ax.set_ylabel('Log2 contrast, recorded reference')
        if len(f):ax.legend(fontsize=5)
        else:empty(ax)
    save('kinase_footprints','kinase/kinase_temporal_profiles',lambda ax,f:curves(ax,f,'candidate_id','activity_magnitude','curated_A'),'first 12 stable candidate/arm/reference series; curated track; gaps remain gaps')
    save('protein_trajectories','quant/protein_contrasts',lambda ax,f:curves(ax,f,'protein_group','log2_change'),'first 12 stable protein/arm/reference series; all proteins in source')
    def heat(ax,f,index,column,value):
        if f.empty:return empty(ax)
        # IDs are explicit; no aggregation across arms/references or unobserved values.
        grid=f.pivot_table(index=index,columns=column,values=value,aggfunc='first',dropna=False).sort_index().iloc[:50]
        if grid.empty:return empty(ax)
        cmap=plt.get_cmap('coolwarm').with_extremes(bad='#bdbdbd')
        image=ax.imshow(np.ma.masked_invalid(grid.to_numpy(float)),aspect='auto',cmap=cmap)
        ax.set_xticks(range(len(grid.columns)),list(map(str,grid.columns)),rotation=45,ha='right',fontsize=6)
        ax.set_yticks(range(len(grid)),list(map(str,grid.index)),fontsize=5);ax.figure.colorbar(image,ax=ax)
    save('substrate_contrast_heatmap','quant/comparisons',lambda ax,f:heat(ax,f,'form_id','contrast_id','A'),'first 50 stable form IDs, every explicit contrast; NA gray')
    save('emerging_detection','evidence/emergence_evidence',lambda ax,f:heat(ax,f,'form_id','condition_id','detected_n'),'first 50 stable forms, actual condition detection counts; shared observations not independent replicates')
    def timing(ax,f):
        f=f.dropna(subset=['source_peak_min','target_peak_min'])
        if len(f):ax.scatter(f.source_peak_min,f.target_peak_min,s=12,alpha=.35)
        else:empty(ax)
        ax.set_xlabel('Source observed peak time (minutes)');ax.set_ylabel('Target observed peak time (minutes)')
    save('cross_layer_timing','temporal/cross_layer_links',timing,'all finite supported cross-layer links; sampled peaks are not causal lag estimates')
    json_write(output/'figure_legends.json',legends)
