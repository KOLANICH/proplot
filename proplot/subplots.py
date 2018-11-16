#!/usr/bin/env python3
import re
import numpy as np
# import io
# from contextlib import redirect_stdout
import matplotlib.pyplot as plt
# Local modules, projection sand formatters and stuff
try:
    from icecream import ic
except ImportError:  # graceful fallback if IceCream isn't installed.
    ic = lambda *a: None if not a else (a[0] if len(a) == 1 else a) # noqa
from .rcmod import rc
from .gridspec import _gridspec_kwargs, FlexibleGridSpec
from . import base
from .utils import _fill
from functools import wraps

#------------------------------------------------------------------------------#
# Miscellaneous helper functions
#------------------------------------------------------------------------------#
def figure(*args, **kwargs):
    """
    Simple alias for 'subplots', perhaps more intuitive.
    """
    return subplots(*args, **kwargs)

def close():
    """
    Close all figures 'open' in memory. This does not delete images printed
    in an ipython notebook; those are rendered versions of the abstract figure objects.
    """
    plt.close('all') # easy peasy

def show():
    """
    Show all figures.
    """
    plt.show()

#-------------------------------------------------------------------------------
# Primary plotting function; must be used to create figure/axes if user wants
# to use the other features
#-------------------------------------------------------------------------------
class axes_list(list):
    """
    Magical clas that iterates through each axes and calls respective
    method on each one. Returns a list of each return value.
    """
    def __repr__(self):
        # Make clear that this is no ordinary list
        return 'axes_list(' + super().__repr__() + ')'

    def __getitem__(self, key):
        # Return an axes_list version of the slice, or just the axes
        axs = list.__getitem__(self, key)
        if isinstance(key,slice): # i.e. returns a list
            axs = axes_list(axs)
        return axs

    def __getattr__(self, attr):
        # Stealthily return dummy function that actually iterates
        # through each attribute here
        values = [getattr(ax, attr, None) for ax in self]
        if None in values:
            raise AttributeError(f"'{type(self[0])}' object has no method '{attr}'.")
        elif all(callable(value) for value in values):
            @wraps(values[0])
            def iterator(*args, **kwargs):
                ret = []
                for ax in self:
                    res = getattr(ax, attr)(*args, **kwargs)
                    if res is not None:
                        ret += [res]
                return None if not ret else ret[0] if len(ret)==1 else ret
            return iterator
        elif all(not callable(value) for value in values):
            return values[0] if len(values)==1 else values # just return the attribute list
        else:
            raise AttributeError('Mixed methods found.')

def subplots(array=None, ncols=1, nrows=1, rowmajor=True, # allow calling with subplots(array)
        emptycols=[], emptyrows=[], # obsolete?
        tight=None, auto_adjust=True,
        # tight=True, adjust=False,
        rcreset=True, silent=True, # arguments for figure instantiation
        sharex=True, sharey=True, # for sharing x/y axis limits/scales/locators for axes with matching GridSpec extents, and making ticklabels/labels invisible
        spanx=True,  spany=True,  # custom setting, optionally share axis labels for axes with same xmin/ymin extents
        innerpanels={}, innercolorbars={}, innerpanels_kw={},
        basemap=False, proj={}, projection={}, proj_kw={}, projection_kw={},
        **kwargs): # for projections; can be 'basemap' or 'cartopy'
    """
    Summary
    -------
    Special creation of subplots grids, allowing for arbitrarily overlapping 
    axes objects. Will return figure handle and axes objects.

    Details
    -------
    * Easiest way to create subplots is with nrows=1 and ncols=1. If you want extra space
      between a row or column, specify the row/column number that you want to be 'empty' with
      emptyrows=row/emptycolumn=column, and adjust wratios/hratios for the desired width of that space.
    * For more complicated plots, can pass e.g. array=[[1,2,3,4],[0,5,5,0]] to create a grid
      of 4 plots on the top, single plot spanning the middle 2-columns on the bottom, and empty
      spaces where the 0 appears.
    * Use bottompanel/bottompanels to make several or multiple panels on the bottom
      that can be populated with multiple colorbars/legend; bottompanels=True will
      just make one 'space' for every column, and bottompanels=[1,1,2] for example will
      make a panel spanning the first two columns, then a single panel for the final column.
      This will add a bottompanel attribute to the figure; can index that attribute if there
      are multiple places for colorbars/legend.
    * Initialize cartopy plots with package='basemap' or package='cartopy'. Can control which plots
      we want to be maps with maps=True (everything) or maps=[numbers] (the specified subplot numbers).

    Notes
    -----
    * Matplotlib set_aspect option seems to behave strangely on some plots (trend-plots from
        SST paper); for this reason we override the fix_aspect option provided by basemap and
        just draw figure with appropriate aspect ratio to begin with. Otherwise get weird
        differently-shaped subplots that seem to make no sense.
    * Shared axes will generally end up with the same axis limits/scaling/majorlocators/minorlocators;
        the sharex and sharey detection algorithm really is just to get instructions to make the
        ticklabels/axis labels invisible for certain axes.

    Todo
    ----
    * Generalize axes sharing for right y-axes and top x-axes. Enable a secondary
      axes sharing mode where we *disable ticklabels and labels*, but *do not
      use the builtin sharex/sharey API*, suitable for complex map projections.
    * For spanning axes labels, right now only detect **x labels on bottom**
        and **ylabels on top**; generalize for all subplot edges.
    * Figure size should be constrained by the dimensions of the axes, not vice
        versa; might make things easier.
    """
    # Helper functions
    translate = lambda p: {'bottom':'b', 'top':'t', 'right':'r', 'left':'l'}.get(p, p)
    auto_adjust = _fill(tight, auto_adjust)
    def axes_dict(value, kw=False):
        # First build up dictionary
        # Accepts:
        # 1) 'string' or {1:'string1', (2,3):'string2'}
        if not kw:
            if not isinstance(value, dict):
                value = {range(1,num_axes+1): value}
        # 2) {'prop':value} or {1:{'prop':value1}, (2,3):{'prop':value2}}
        else:
            nested = [isinstance(value,dict) for value in value.values()]
            if not any(nested): # any([]) == False
                value = {range(1,num_axes+1): value.copy()}
            elif not all(nested):
                raise ValueError('Wut.')
        # Then unfurl wherever keys contain multiple axes numbers
        kw_out = {}
        for nums,item in value.items():
            nums = np.atleast_1d(nums)
            for num in nums.flat:
                kw_out[num-1] = item
        # Verify numbers
        if {*range(num_axes)} != {*kw_out.keys()}:
            raise ValueError(f'Have {num_axes} axes, but {value} only has properties for axes {", ".join(str(i+1) for i in sorted(kw_out.keys()))}.')
        return kw_out

    # Array setup
    if array is None:
        array = np.arange(1,nrows*ncols+1)[...,None]
        order = 'C' if rowmajor else 'F' # for column major, use Fortran ordering
        array = array.reshape((nrows, ncols), order=order) # numpy is row-major, remember
    array = np.array(array) # enforce array type
    if array.ndim==1:
        array = array[None,:] if rowmajor else array[:,None] # interpret as single row or column
    # Empty rows/columns feature
    array[array==None] = 0 # use zero for placeholder; otherwise have issues
    if emptycols:
        emptycols = np.atleast_1d(emptycols)
        for col in emptycols.flat:
            array[:,col-1] = 0
    if emptyrows:
        emptyrows = np.atleast_1d(emptyrows)
        for row in emptyrows.flat:
            array[row-1,:] = 0
    # Enforce rule
    nums = np.unique(array[array!=0])
    num_axes = len(nums)
    if tuple(nums.flat) != tuple(range(1,num_axes+1)):
        raise ValueError('Axes numbers must span integers 1 to num_axes (i.e. cannot skip over numbers).')
    nrows = array.shape[0]
    ncols = array.shape[1]

    # Get basemap.Basemap or cartopy.CRS instances for map, and override aspec tratio
    # NOTE: Previously went to some pains (mainly for basemap, something in the
    # initialization deals with this) to only draw one projection. This is hard
    # to generalize when want different projections/kwargs, so abandon
    basemap = axes_dict(basemap, False) # package used for projection
    proj = axes_dict(projection or proj or 'xy', False) # name of projection; by default use base.XYAxes
    proj_kw = axes_dict(projection_kw or proj_kw, True) # stores cartopy/basemap arguments
    axes_kw = {num:{} for num in range(num_axes)} # stores add_subplot arguments
    for num,name in proj.items():
        # Builtin matplotlib polar axes, just use my overridden version
        if name=='polar':
            axes_kw[num]['projection'] = 'newpolar'
            if num==1:
                kwargs.update(aspect=1)
        # The default, my XYAxes projection
        elif name=='xy':
            axes_kw[num]['projection'] = 'xy'
        # Custom Basemap and Cartopy axes
        elif name:
            package = 'basemap' if basemap[num] else 'cartopy'
            instance, aspect = base.map_projection_factory(package, name, **proj_kw[num])
            axes_kw[num].update({'projection':package, 'map_projection':instance})
            if not silent:
                print(f'Forcing aspect ratio: {aspect:.3g}')
            if num==1:
                kwargs.update(aspect=aspect)
        else:
            raise ValueError('All projection names should be declared. Wut.')

    # Create dictionary of panel toggles and settings
    # Input can be string e.g. 'rl' or dictionary e.g. {(1,2,3):'r', 4:'l'}
    # NOTE: Internally we convert array references to 0-base here
    # Add kwargs and the 'which' arguments
    # Optionally change the default panel widths for 'colorbar' panels
    if not isinstance(innercolorbars, (dict, str)):
        raise ValueError('Must pass string of panel sides or dictionary mapping axes numbers to sides.')
    if not isinstance(innerpanels, (dict, str)):
        raise ValueError('Must pass string of panel sides or dictionary mapping axes numbers to sides.')
    innerpanels = axes_dict(innerpanels or '', False)
    innercolorbars = axes_dict(innercolorbars or '', False)
    innerpanels_kw = axes_dict(innerpanels_kw, True)
    for num,which in innerpanels.items():
        innerpanels_kw[num]['whichpanels'] = translate(which)
    for num,which in innercolorbars.items():
        which = translate(which)
        if which:
            innerpanels_kw[num]['whichpanels'] = which
            if re.search('[bt]', which):
                kwargs['hspace'] = _fill(kwargs.get('hspace',None), rc['gridspec.xlab'])
                innerpanels_kw[num]['sharex_panels'] = False
                innerpanels_kw[num]['hwidth'] = _fill(innerpanels_kw[num].get('hwidth', None), rc['gridspec.cbar'])
                innerpanels_kw[num]['hspace'] = _fill(innerpanels_kw[num].get('hspace', None), rc['gridspec.xlab'])
            if re.search('[lr]', which):
                kwargs['wspace'] = _fill(kwargs.get('wspace',None), rc['gridspec.ylab'])
                innerpanels_kw[num]['sharey_panels'] = False
                innerpanels_kw[num]['wwidth'] = _fill(innerpanels_kw[num].get('wwidth', None), rc['gridspec.cbar'])
                if 'l' in which and 'r' in which:
                    default = (rc['gridspec.ylab'], rc['gridspec.nolab'])
                elif 'l' in which:
                    default = rc['gridspec.ylab']
                else:
                    default = rc['gridspec.nolab']
                innerpanels_kw[num]['wspace'] = _fill(innerpanels_kw[num].get('wspace', None), default)

    # Create gridspec for outer plotting regions (divides 'main area' from side panels)
    figsize, offset, subplots_kw, gridspec_kw = _gridspec_kwargs(nrows, ncols, **kwargs)
    row_offset, col_offset = offset
    gs = FlexibleGridSpec(**gridspec_kw)
    fig = plt.figure(figsize=figsize, auto_adjust=auto_adjust, rcreset=rcreset,
        gridspec=gs, subplots_kw=subplots_kw,
        FigureClass=base.Figure,
        )

    #--------------------------------------------------------------------------
    # Manage shared axes/axes with spanning labels
    #--------------------------------------------------------------------------
    # Get some axes properties
    # Note that these locations should be **sorted** by axes id
    axes_ids = [np.where(array==i) for i in np.unique(array) if i>0] # 0 stands for empty
    yrange = row_offset + np.array([[xy[0].min(), xy[0].max()+1] for xy in axes_ids]) # yrange is shared columns
    xrange = col_offset + np.array([[xy[1].min(), xy[1].max()+1] for xy in axes_ids])
    # asdfas
    # xmin   = np.array([xy[0].min() for xy in axes_ids]) # unused
    # ymax   = np.array([xy[1].max() for xy in axes_ids])

    # Shared axes: generate list of base axes-dependent axes pairs
    # That is, find where the minimum-maximum gridspec extent in 'x' for a
    # given axes matches the minimum-maximum gridspec extent for a base axes
    xgroups_base, xgroups_sorted, xgroups, grouped = [], [], [], []
    if sharex:
        for i in range(num_axes): # axes now have pseudo-numbers from 0 to num_axes-1
            matches       = (xrange[i,:]==xrange).all(axis=1) # *broadcasting rules apply here*
            matching_axes = np.where(matches)[0] # gives ID number of matching_axes, from 0 to num_axes-1
            if i not in grouped and matching_axes.size>1:
                # Find all axes that have the same gridspec 'x' extents
                xgroups      += [matching_axes]
                # Get bottom-most axis with shared x; should be single number
                # xgroups_base += [matching_axes[np.argmax(yrange[matching_axes,1])]]
                xgroups_base += [matching_axes[np.argmax(yrange[matching_axes,1])]]
                # Sorted group
                xgroups_sorted += [matching_axes[np.argsort(yrange[matching_axes,1])[::-1]]] # bottom-most axes is first
            grouped += [*matching_axes] # bookkeeping; record ids that have been grouped already
    ygroups_base, ygroups_sorted, ygroups, grouped = [], [], [], []
    if sharey:
        for i in range(num_axes):
            matches       = (yrange[i,:]==yrange).all(axis=1) # *broadcasting rules apply here*
            matching_axes = np.where(matches)[0]
            if i not in grouped and matching_axes.size>1:
                ygroups      += [matching_axes]
                ygroups_base += [matching_axes[np.argmin(xrange[matching_axes,0])]] # left-most axis with shared y, for matching_axes
                ygroups_sorted += [matching_axes[np.argsort(xrange[matching_axes,0])]] # left-most axis is first
            grouped += [*matching_axes] # bookkeeping; record ids that have been grouped already

    #--------------------------------------------------------------------------
    # Draw axes
    # TODO: Need to configure to automatically determine 'base' axes based on
    # what has already been drawn. Not critical but would be nice.
    # TODO: Need to do something similar for the spanning axes. Also will
    # allow label to be set on any of the axes, but when this happens, will
    # set the label on the 'base' spanning axes.
    #--------------------------------------------------------------------------
    # Base axes; to be shared with other axes as ._sharex, ._sharey attributes
    axs = num_axes*[None] # list of axes
    allgroups_base = []
    if sharex:
        allgroups_base += xgroups_base
    if sharey:
        allgroups_base += ygroups_base
    for i in allgroups_base:
        ax_kw = axes_kw[i]
        if axs[i] is not None: # already created
            continue
        if innerpanels_kw[i]['whichpanels']: # non-empty
            axs[i] = fig.panel_factory(gs[slice(*yrange[i,:]), slice(*xrange[i,:])],
                    spanx=spanx, spany=spany,
                    number=i+1, **ax_kw, **innerpanels_kw[i]) # main axes handle
        else:
            axs[i] = fig.add_subplot(gs[slice(*yrange[i,:]), slice(*xrange[i,:])],
                    spanx=spanx, spany=spany,
                    number=i+1, **ax_kw) # main axes can be a cartopy projection

    # Dependent axes
    for i in range(num_axes):
        # Detect if we want to share this axis with another. If so, get that
        # axes. Also do some error checking
        sharex_ax, sharey_ax = None, None # by default, don't share with other axes objects
        ax_kw = axes_kw[i]
        if sharex:
            igroup = np.where([i in g for g in xgroups])[0]
            if igroup.size==1:
                sharex_ax = axs[xgroups_base[igroup[0]]]
                if sharex_ax is None:
                    raise ValueError('Something went wrong; shared x axes was not already drawn.')
        if sharey:
            igroup = np.where([i in g for g in ygroups])[0] # np.where works on lists
            if igroup.size==1:
                sharey_ax = axs[ygroups_base[igroup[0]]]
                if sharey_ax is None:
                    raise ValueError('Something went wrong; shared x axes was not already drawn.')

        # Draw axes, and add to list
        if axs[i] is not None:
            # Axes is a *base* and has already been drawn, but might still
            # have shared axes (e.g. is bottom-axes of three-column plot
            # and we want it to share the leftmost y-axis)
            if sharex_ax is not None and axs[i] is not sharex_ax:
                axs[i]._sharex_setup(sharex_ax)
            if sharey_ax is not None and axs[i] is not sharey_ax:
                axs[i]._sharey_setup(sharey_ax)
        else:
            # Virgin axes; these are not an x base or a y base
            if innerpanels_kw[i]['whichpanels']: # non-empty
                axs[i] = fig.panel_factory(gs[slice(*yrange[i,:]), slice(*xrange[i,:])],
                        number=i+1, spanx=spanx, spany=spany,
                        sharex=sharex_ax, sharey=sharey_ax, **ax_kw, **innerpanels_kw[i])
            else:
                axs[i] = fig.add_subplot(gs[slice(*yrange[i,:]), slice(*xrange[i,:])],
                        number=i+1, spanx=spanx, spany=spany,
                        sharex=sharex_ax, sharey=sharey_ax, **ax_kw) # main axes can be a cartopy projection

    # Check that axes don't belong to multiple groups
    # This should be impossible unless my code is completely wrong...
    for ax in axs:
        for name,groups in zip(('sharex', 'sharey'), (xgroups, ygroups)):
            if sum(ax in group for group in xgroups)>1:
                raise ValueError(f'Something went wrong; axis {i:d} belongs to multiple {name} groups.')

    #--------------------------------------------------------------------------#
    # Create panel axes
    #--------------------------------------------------------------------------#
    def _paneladd(name, panels):
        if not panels:
            return
        axsp = []
        side = re.sub('^(.*)panel$', r'\1', name)
        for n in np.unique(panels).flat:
            offset = row_offset if side in ('left','right') else col_offset
            idx, = np.where(panels==n)
            idx = slice(offset + min(idx), offset + max(idx) + 1)
            if side=='right':
                subspec = gs[idx,-1]
            elif side=='left':
                subspec = gs[idx,0]
            elif side=='bottom':
                subspec = gs[-1,idx]
            axp = fig.add_subplot(subspec, panel_side=side, invisible=True, projection='panel')
            axsp += [axp]
        setattr(fig, name, axes_list(axsp))
    _paneladd('bottompanel', subplots_kw.bottompanels)
    _paneladd('rightpanel',  subplots_kw.rightpanels)
    _paneladd('leftpanel',   subplots_kw.leftpanels)

    #--------------------------------------------------------------------------
    # Return results
    # Will square singleton arrays
    #--------------------------------------------------------------------------
    if not silent:
        print('Figure setup complete.')
    # if len(axs)==1:
    #     axs = axs[0]
    # return fig, axs
    return fig, axes_list(axs)
