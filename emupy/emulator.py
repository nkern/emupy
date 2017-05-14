"""
emulator.py
============

An emulator in Python

Nicholas Kern
nkern@berkeley.edu
"""

# Import Modules
from __future__ import division
import os
import sys
import numpy as np
import scipy.linalg as la
import fnmatch
from .scripts.DictEZ import create as ezcreate
import itertools
import operator
import functools
from sklearn import gaussian_process
from sklearn import neighbors
import astropy.stats as astats

try: from memory_profiler import memory_usage
except: pass

__all__ = ['Emu']

class Emu(object):
    """
    Emulator class object
    ---------------------

    In order for the methods of Emu to work properly, there are a few objects that
    need to be attached to the class namespace beforehand. This varies slightly from 
    method-to-method, but generally one will need those listed below. Note that one can
    easily append/overwrite objects to the class namespace by feeding Emu.update(dic), 
    where dic is a dictionary containing the objects.

    grid_tr : ndarray [dtype=float, shape=(N_samples, N_dim)]
        ndarray containing positions of training data in parameter space

    data_tr : ndarray [dtype=float, shape=(N_samples, N_data)]
        ndarray containing data of training data

    fid_grid : ndarray [dtype=float, shape=(N_dim)]
        average or fiducial parameter vector of training set

    fid_data : ndarray [dtype=float, shape=(N_data)]
        average or fiducial data vector of training data

    cov_est : object [default=np.cov]
        function object that is a covariance estimator

    lognorm : bool [default=False]
        if True, log-transform training data before emulation

    scale_by_std : bool [default=False]
        if True, scale training data by standard deviation
        before emulation

    scale_by_yerrs : bool [default=False]
        if True, scale training data by observational errors
        before emulation

    rescale : ndarray [default=None]
        if not None, rescaling matrix for rescaling training data
        before emulation

    rescale_power : float [default=None]
        if note None, exponential of rescaling matrix before rescaling

    recon_calib : float or ndarray [default=1.0]
        multiplicative factor of emulator predicted reconstructions

    recon_err_calib : float or ndarray [default=1.0]
        multiplicative factor of emulator predicted reconstruction errors

    w_norm : float or ndarray [default=1.0]
        multiplicative factor of PCA weights before emulation

    """

    def __init__(self):
        self.__name__           = 'Emu'
        self._trained           = False
        self.cov_est            = np.cov
        self.lognorm            = False
        self.scale_by_std       = False
        self.scale_by_yerrs     = False
        self.rescale            = None
        self.rescale_power      = None
        self.recon_calib        = 1.0
        self.recon_err_calib    = 1.0
        self.w_norm             = 1.0

    @property
    def print_pars(self):
        """
        print parameters in class dictionary
        """
        keys = self.__dict__.keys()
        vals = self.__dict__.values()
        sort = np.argsort(keys)
        string = "\n" + "-"*5 + "    " + "Class Parameters" + "    " + "-"*5 + "\n" + "="*40 + "\n"
        for i in range(len(keys)):
            if type(vals[sort[i]])==np.int or type(vals[sort[i]])==np.str or type(vals[sort[i]])==np.float or type(vals[sort[i]])==np.bool:
                string += keys[sort[i]] + '\r\t\t\t = ' + str(vals[sort[i]]) + '\n'
        print string

    def update(self, dic):
        """
        update class dictionary

        Input:
        ------
        dic : dictionary
        """
        self.__dict__.update(dic)

    def sphere(self, grid, fid_grid=None, save_chol=False, invL=None, attach=True, norotate=False):
        """
        Perform Cholesky decomposition to sphere data into whitened basis

        Input:
        ------
        grid : ndarray [arg, dtype=float, shape=(N_samples, N_dim)]
            ndarray of N_samples grid points in an N_dim dimensional parameter space

        fid_grid : ndarray [kwarg, dtype=float, shape=(N_dim,), default=None]
            1D numpy array of average (or fiducial) grid point

        save_chol : bool [kwarg, default=False]
            if True, overwrite the used Cholesky to class namespace 

        invL : ndarray [kwwarg, dtype=float, shape=(N_dim, N_dim), default=None]
            precomputed inverse cholesky to use for whitening

        attach : bool [kwarg, default=True]
            if True, attach sphered grid ("Xsph") to class namespace

        norotate : bool [kwarg, default=False]
            if True, set off-diagonal elements of Cholesky to zero, such that
            the whitened basis is aligned with cartesian axis. 

        Requires:
        ---------
        cov_est : class method
            covariance estimator
        """
        # Get fiducial points
        if fid_grid is None:
            fid_grid = np.array(map(np.median,grid.T))

        # Subtract mean
        X = grid - fid_grid

        if invL is None:
            # Find Covariance
            Xcov = self.cov_est(X.T)# np.cov(X.T, ddof=1) #np.inner(X.T,X.T)/self.N_samples
            if Xcov.ndim < 2:
                Xcov = np.array([[Xcov]])
            # Find cholesky
            L = la.cholesky(Xcov).T
            if norotate == True:
                L = np.eye(len(L)) * L.diagonal()
            invL = la.inv(L)

        # Save cholesky
        if save_chol == True:
            self.grid_tr = params
            self.fid_params = fid_params
            self.L = L
            self.invL = invL

        # Transform to non-covarying basis
        Xsph = np.dot(invL, X.T).T
        if attach == True:
            self.Xsph = Xsph
        else:
            return Xsph

    def create_tree(self, data, tree_type='ball', leaf_size=100, metric='euclidean'):
        """
        create tree structure from grid points

        Input:
        ------
        grid : ndarray [arg, dtype=float, shape=(N_samples, N_dim)]
            ndarray of grid points in parameter space

        tree_type : str [kwarg, default='ball', options=('ball','kd')]
            type of tree to make

        leaf_size : int [kwarg, default=100]
            tree leaf size, see sklearn.neighbors documentation for details

        metric : str [kwarg, default='euclidean']
            distance metric, see sklearn.neighbors documentation for details

        Output:
        -------
        no output, creates self.tree object
        """
        if tree_type == 'ball':
            self.tree = neighbors.BallTree(data,leaf_size=leaf_size,metric=metric)
        elif tree_type == 'kd':
            self.tree = neighbors.KDTree(data,leaf_size=leaf_size,metric=metric)

    def nearest(self, theta, k=10, use_tree=False):
        """
        perform a nearest neighbor search of grid from theta

        Input:
        ------
        theta : ndarray [arg, dtype=float, shape=(N_dim)]
            point in parameter space to perform nearest neighbor search from

        k : int [kwarg, default=10]
            number of nearest neighbors to query

        use_tree : bool [kwarg, default=False]
            if True, use tree structure to make query, else use brute-force search

        Output:
        -------

        """
        if use_tree == True:
            if hasattr(self, 'tree')
                # Make tree if not present
                self.sphere(self.grid_tr, fid_grid=self.fid_grid, invL=self.invL)
                self.create_tree(self.Xsph)
            grid_D, grid_NN = self.tree.query(theta, k=k+1)
            if theta.ndim == 1:
                grid_D, grid_NN = grid_D[0], grid_NN[0]
        else:
            if theta.ndim > 1:
                near = np.array(map(lambda x: np.argsort(map(la.norm, self.Xsph-x)), theta))
                grid_D = np.array([map(lambda x: la.norm, self.Xsph[near[i][:k+1]]-theta[i]) for i in range(len(near))])
                grid_NN = np.array(map(lambda x: x[:k+1], near))
            else:
                near = np.argsort(np.array(map(la.norm, self.Xsph-theta)))
                grid_D = np.array(map(la.norm, self.Xsph[near][:k+1]-theta))
                grid_NN = near[:k+1]

        if grid_D[0] == 0:
            grid_D = grid_D[1:]
            grid_NN = grid_NN[1:]
        else:
            grid_D = grid_D[:-1]
            grid_NN = grid_NN[:-1]

        return grid_D, grid_NN

    def poly_design_mat(self,Xrange,dim=2,degree=6):
        """
        - Create polynomial design matrix given discrete values for dependent variables
        - dim : number of dependent variables 
        - degree : degree of polynomial to fit
        - Xrange is a list with dim # of arrays, with each array containing
            discrete values of the dependent variables that have been unraveled for dim > 1
        - Xrange has shape dim x Ndata, where Ndata is the # of discrete data points
        - A : Ndata x M design matrix, where M = (dim+degree)!/(dim! * degree!)
        - Example of A for dim = 2, degree = 2, Ndata = 3:
            A = [   [ 1  x  y  x^2  y^2  xy ]
                    [ 1  x  y  x^2  y^2  xy ]
                    [ 1  x  y  x^2  y^2  xy ]   ]
        """

        # Generate all permutations
        perms = itertools.product(range(degree+1),repeat=dim)
        perms = np.array(map(list,perms))

        # Take the sum of the powers, sort, and eliminate sums > degree
        sums = np.array(map(lambda x: reduce(operator.add,x),perms))
        argsort = np.argsort(sums)
        sums = sums[argsort]
        keep = np.where(sums <= degree)[0]
        perms = perms[argsort][keep]

        # Create design matrix
        to_the_power = lambda x,y: np.array(map(lambda z: x**z,y))
        dims = []
        for i in range(dim):
            dims.append(to_the_power(Xrange[i],perms.T[i]).T)
        dims = np.array(dims)

        A = np.array(map(lambda y: map(lambda x: functools.reduce(operator.mul,x),y),dims.T)).T

        return A

    def chi_square_min(self,y,A,N,regulate=False,fast=False):
        '''
        - perform chi square minimization
        - A is data model
        - N are weights of each y_i for fit
        - y are dataset
        '''
        # Solve for coefficients xhat
        if regulate == True:
            coeff = np.dot( np.dot(A.T,la.inv(N)), A)
            coeff_diag = np.diagonal(coeff)
            penalty = coeff_diag.mean()/1e10 * np.eye(A.shape[1])
            xhat = np.dot( la.inv(coeff + penalty), np.dot( np.dot(A.T,la.inv(N)), y) )
        else:
            xhat = np.dot( la.inv( np.dot( np.dot(A.T,la.inv(N)), A)), np.dot( np.dot(A.T,la.inv(N)), y) )

        if fast == True:
            return xhat, np.zeros(A.shape)
        else:
            # Get error
            Ashape = A.shape
            resid = (y - np.dot(A,xhat))
            sq_err = np.abs(np.dot(resid.T,resid)/(Ashape[0]-Ashape[1]))
            return xhat, np.sqrt(sq_err)

    def klt(self,data_tr,fid_data=None,normalize=False,w_norm=None):
        ''' compute KL transform and calculate eigenvector weights for each sample in training set (TS)
            data        : [N_samples, N_data] 2D matrix, containing data of TS
            fid_data    : [N_data] row vector, containing fiducial data

            Necessary parameters when initializing klfuncs:
            N_modes     : scalar, number of eigenmodes to keep after truncation
            N_samples   : scalar, number of samples in training set
        '''
        
        # Compute fiducial data set
        if fid_data is None:
            if self.lognorm == True:
                fid_data = np.exp(np.array(map(astats.biweight_location, np.log(data_tr.T))))
            else:
                fid_data = np.array(map(astats.biweight_location, data_tr.T))

        # Find self-variance of mean-subtracted data
        if self.lognorm == True:
            D = np.log(data_tr / fid_data)
        else:
            D = (data_tr - fid_data)

        if self.scale_by_std == True:
            self.Dstd = np.array(map(astats.biweight_midvariance,D.T))
            D /= self.Dstd

        if self.scale_by_yerrs == True:
            if self.rescale is not None:
                if self.lognorm == True:
                    self.rescale = self.yerrs/fid_data
                else:
                    self.rescale = self.yerrs
            if self.rescale_power is not None:
                self.rescale = self.rescale**self.rescale_power
            D /= self.rescale

        # Find Covariance
        Dcov = self.cov_est(D.T) #np.cov(D.T, ddof=1) #np.inner(D.T,D.T)/self.N_samples

        # Solve for eigenvectors and values using SVD
        u,eig_vals,eig_vecs = la.svd(Dcov)

        # Sort by eigenvalue
        eigen_sort = np.argsort(eig_vals)[::-1]
        eig_vals = eig_vals[eigen_sort]
        eig_vecs = eig_vecs[eigen_sort]

        # Solve for per-sample eigenmode weight constants
        w_tr = np.dot(D,eig_vecs.T)

        # Truncate eigenmodes to N_modes # of modes
        eig_vals        = eig_vals[:self.N_modes]
        eig_vecs        = eig_vecs[:self.N_modes]
        w_tr            = w_tr[:,:self.N_modes]
        tot_var         = sum(eig_vals)
        rec_var         = sum(eig_vals[:self.N_modes])
        frac_var        = rec_var/tot_var

        if normalize == True and w_norm is None:
            w_norm = np.sqrt(eig_vals)
            w_norm = np.array(map(lambda x: astats.biweight_midvariance(x)*5, w_tr.T)).T

        elif normalize == True and w_norm is not None:
            w_norm = w_norm

        elif normalize == False:
            w_norm = np.ones(self.N_modes)

        w_tr /= w_norm

        # Update to Namespace
        names = ['D','data_tr','Dcov','eig_vals','eig_vecs','w_tr','tot_var','rec_var','frac_var','fid_data','w_norm']
        self.update(ezcreate(names,locals()))

    def klt_project(self,data):
        '''
        Having already run klt() to get eigenvectors and eigenvalues, project vector 'data' onto eigenmodes
        '''
        # Subtract fiducial data from data
        if self.lognorm == True:
            D = np.log(data / self.fid_data)
        else:
            D = data - self.fid_data

        if self.scale_by_std == True:
            D /= self.Dstd

        if self.scale_by_yerrs == True:
            D /= self.rescale

        # Project onto eigenvectors
        self.w_tr = np.dot(D,self.eig_vecs.T)
        self.w_tr /= self.w_norm

    def kfold_cv(self,grid_tr,data_tr,use_pca=True,predict_kwargs={},
                   rando=None, kfold_Nclus=None, kfold_Nsamp=None, kwargs_tr={},
                   RandomState=1, pool=None, vectorize=True):
        """
        Cross validate emulator

        Input:
        ------
        grid_tr : ndarray

        data_tr : ndarray

        use_pca : bool (default=True)

        predict_kwargs : dict (default={})

        data_tr : ndarray (default=None)

        grid_tr : ndarray (default=None)

        kfold_Nclus : int (default=None)
        
        kfold_Nsamp : int (default=None)

        kwargs_tr : dict (default={})

        RandomState : int (default=1)

        Output:
        -------
        recon_cv
        recon_err_cv
        recon_grid
        """
        # Assign random cv sets
        if rando is None:
            rd = np.random.RandomState(RandomState)
            size = kfold_Nclus*kfold_Nsamp
            rando = rd.choice(np.arange(len(data_tr)), replace=False, size=size).reshape(kfold_Nclus,kfold_Nsamp)
            rando = np.array([map(lambda x: x in rando[i], np.arange(len(data_tr))) for i in range(kfold_Nclus)])

        # Iterate over sets
        recon_grid = []
        recon_data = []
        recon_cv = []
        recon_err_cv = []
        weights_cv = []
        weights_err_cv = []
        weights_true = []
        for i in range(kfold_Nclus):
            print "...working on kfold clus "+str(i+1)+":\n"+"-"*26
            data_tr_temp = data_tr[~rando[i]]
            grid_tr_temp = grid_tr[~rando[i]]
            # Train     
            self.train(data_tr_temp,grid_tr_temp,fid_data=self.fid_data,fid_params=self.fid_params,**kwargs_tr)
            # Cross Valid
            self.cross_validate(grid_tr[rando[i]], data_tr[rando[i]], use_pca=use_pca, predict_kwargs=predict_kwargs, vectorize=vectorize)
            recon_cv.extend(self.recon_cv)
            recon_err_cv.extend(self.recon_err_cv)
            recon_grid.extend(np.copy(grid_tr[rando[i]]))
            recon_data.extend(np.copy(data_tr[rando[i]]))
            weights_cv.extend(self.weights_cv)
            weights_err_cv.extend(self.weights_err_cv)
            weights_true.extend(self.weights_true_cv)

        recon_cv = np.array(recon_cv)
        recon_err_cv = np.array(recon_err_cv)
        recon_grid = np.array(recon_grid)
        recon_data = np.array(recon_data)
        weights_cv = np.array(weights_cv)
        weights_err_cv = np.array(weights_err_cv)
        weights_true = np.array(weights_true)

        return recon_cv, recon_err_cv, recon_grid, recon_data, weights_cv, weights_err_cv, weights_true, rando

    def cross_validate(self,grid_cv,data_cv,use_pca=True,predict_kwargs={},output=False,LAYG=False,use_tree=False,
                    vectorize=True,pool=None):

        # Solve for eigenmode weight constants
        if use_pca == True:
            self.klt_project(data_cv)
            self.weights_true_cv = self.w_tr * self.w_norm

        # Set-up iterator
        if pool is None:
            M = map
        else:
            M = pool.map

        # Predict
        if LAYG == True:
            if grid_cv.ndim == 1: grid_cv = grid_cv[np.newaxis,:]
            recon,recon_err,recon_err_cov,weights,weights_err = [],[],[],[],[]
            output = M(lambda x: self.predict(x, output=True, use_tree=use_tree, **predict_kwargs), grid_cv)
            for i in range(len(output)):
                recon.append(output[i][0][0])
                recon_err.append(output[i][1][0])
                recon_err_cov.append(output[i][2][0])
                weights.append(output[i][3][0])
                weights_err.append(output[i][4][0])
            recon,recon_err,recon_err_cov = np.array(recon), np.array(recon_err), np.array(recon_err_cov)
            weights, weights_err = np.array(weights), np.array(weights_err)
            self.recon_cv = recon
            self.recon_err_cv = recon_err
            self.recon_err_cov_cv = recon_err_cov
            self.weights_cv = weights
            self.weights_err_cv = weights_err
        else:
            if (vectorize == True and pool is not None) or vectorize == False:
                output = M(lambda x: self.predict(x, output=True, **predict_kwargs), grid_cv)
                recon,recon_err,recon_err_cov,weights,weights_err = [],[],[],[],[]
                for i in range(len(output)):
                    recon.append(output[i][0][0])
                    recon_err.append(output[i][1][0])
                    recon_err_cov.append(output[i][2][0])
                    weights.append(output[i][3][0])
                    weights_err.append(output[i][4][0])
                recon,recon_err,recon_err_cov = np.array(recon), np.array(recon_err), np.array(recon_err_cov)
                weights, weights_err = np.array(weights), np.array(weights_err)

            elif vectorize == True:
                output = self.predict(grid_cv, output=True, **predict_kwargs)
                recon, recon_err, recon_err_cov, weights, weights_err = output

            self.recon_cv = recon
            self.recon_err_cv = recon_err
            self.recon_err_cov_cv = recon_err_cov
            self.weights_cv = weights
            self.weights_err_cv = weights_err

        if output == True:
            return self.recon_cv, self.recon_err_cv, self.recon_err_cov, self.weights_cv, self.weights_err_cv

    def train(self,data,grid,
            fid_data=None,fid_params=None,noise_var=None,gp_kwargs_arr=None,emode_variance_div=1.0,
            use_pca=True,compute_klt=True,norm_noise=False,verbose=False,
            group_modes=False,save_chol=False,invL=None,fast=False,pool=None,norotate=False):
        ''' fit regression model to then be used for interpolation
            noise_var   : [N_samples] row vector with noise variance for each sample in LLS solution

            Necessary parameters when initializing klfuncs:
            N_samples   : scalar, number of samples in TS
            poly_deg    : degree of polynomial to fit for
            scale_by_std    : scale data by its standard dev
            reg_meth    : method of regression, ['poly','gaussian']
            klt() variables
            gp_kwargs variables
        '''
        # Check parameters are correct
        self.param_check(data,grid)

        # Sphere parameter space vector
        if invL is None:
            self.sphere(grid,fid_params=fid_params,norotate=norotate)
            Xsph = self.Xsph
        else:
            Xsph = np.dot(self.invL, (grid-fid_params).T).T

        # Compute y vector
        if compute_klt == True and use_pca == True:
            self.klt(data,fid_data=fid_data)
            y = self.w_tr

        elif compute_klt == False and use_pca == True:
            self.klt_project(data)
            y = self.w_tr

        elif use_pca == False:
            y = data

        if hasattr(self,'N_modegroups') == False:
                self.group_eigenmodes(emode_variance_div=emode_variance_div)

        # polynomial regression
        if self.reg_meth == 'poly':
            # Compute design matrix
            param_samp_ravel = map(list,Xsph.T)
            A = self.poly_design_mat(param_samp_ravel,dim=self.N_params,degree=self.poly_deg)

            # Use LLS over training set to solve for weight function polynomials
            if noise_var is None:
                noise_var = np.array([2]*self.N_samples*self.N_modes)           # all training set samples w/ equal weight
                noise_var = noise_var.reshape(self.N_samples,self.N_modes)

            # Fill weight matrix
            W = np.zeros((self.N_modes,self.N_samples,self.N_samples))
            for i in range(self.N_modes):
                if noise_var is None:
                    np.fill_diagonal(W[i],1e-5)
                elif noise_var is not None:
                    if type(noise_var) == float or type(noise_var) == int:
                        np.fill_diagonal(W[i],noise_var)    
                    else:
                        np.fill_diagonal(W[i],noise_var[i])

            # LLS for interpolation polynomial coefficients
            xhat = []
            stand_err = []
            for i in range(self.N_modes):
                if fast == True:
                    xh = self.chi_square_min(y.T[i],A,W[i],fast=fast)
                    err = 0.0
                else:
                    xh, err = self.chi_square_min(y.T[i],A,W[i],fast=fast)
                xhat.append(xh)
                stand_err.append(err)
            xhat = np.array(xhat).T
            stand_err = np.array(stand_err).T

        # Gaussian Process Regression
        elif self.reg_meth == 'gaussian':
            # Initialize GP, fit to data
            GP = []
            for j in range(self.N_modegroups):
                if gp_kwargs_arr is None:
                    gp_kwargs = self.gp_kwargs.copy()
                else:
                    gp_kwargs = gp_kwargs_arr[j].copy()

                # Create GP
                gp = gaussian_process.GaussianProcessRegressor(**gp_kwargs)
                GP.append(gp)

            # Fit GPs!
            # Use parallel processing for hyperparameter regression (optional)
            def fit(gp, xdata, ydata, modegroups, verbose=False,  message=None):
                gp.fit(xdata, ydata.T[modegroups].T)
                if verbose==True:
                    print(message)

            if pool is None:
                M = map
            else:
                M = pool.map

            message = "...finished modegroup #"
            M(lambda i: fit(GP[i], Xsph, y, self.modegroups[i], verbose=verbose, message=message+str(i)), np.arange(len(GP)))
            GP = np.array(GP)
            if pool is not None:
                pool.close()

        # Update to namespace
        self._trained = True
        names = ['xhat','stand_err','GP']
        self.update(ezcreate(names,locals()))

    def hypersolve_1D(self, grid_od, data_od, kernel=None, n_restarts=4, alpha=1e-3):
        """
        Solve for hyperparameters across each dimension individually
        Make sure norotate = True

        Input:
        ------
        """
        # Rescale grid
        grid_od = np.array(map(lambda x: np.dot(self.invL, (x - self.fid_params).T).T, grid_od))

        # Solve for weights
        self.klt_project(data_od)
        ydata_od = self.w_tr

        # Iterate over independent dimensions
        if kernel is None:
            kernel = gaussian_process.kernels.RBF(length_scale=1.0)

        optima = []
        for p in range(self.N_params):
            xdata = grid_od[p].T[p][:,np.newaxis]
            ydata = ydata_od[p].T
            GP = np.array(map(lambda x: gaussian_process.GaussianProcessRegressor(kernel=kernel, n_restarts_optimizer=n_restarts, alpha=alpha).fit(xdata,x), ydata))
            optima.append(np.array(map(lambda x: x.kernel_.length_scale, GP)))

        optima = np.array(optima).T
        return optima

    def group_eigenmodes(self,emode_variance_div=10.0):
        '''
        - group eigenmodes together based on eigenvalue
        '''
        if emode_variance_div == 1.0:
            self.N_modegroups = self.N_modes
            self.modegroups = np.arange(self.N_modes)[:,np.newaxis]
        elif emode_variance_div > 1e8:
            self.N_modegroups = 1
            self.modegroups = np.arange(self.N_modes)[np.newaxis,:]
        else:   
            eigval_max = self.eig_vals[0]
            eigval_min = self.eig_vals[-1]
            dividers = 10**(np.arange(np.log10(eigval_max),np.log10(eigval_min)+1e-8,-np.log10(emode_variance_div))[1:])
            N_dividers = len(dividers) + 1
            dividers = np.array([np.inf]+list(dividers)+[0])
            modegroups = []
            for i in range(N_dividers):
                select = np.where((self.eig_vals>=dividers[i+1])&(self.eig_vals<dividers[i]))[0]
                if len(select)==0: continue
                modegroups.append(select)
            modegroups=np.array(modegroups)
            N_modegroups = len(modegroups)

            self.N_modegroups = N_modegroups
            self.modegroups = modegroups

    def predict(self,Xpred,use_Nmodes=None,fast=False,pool=None,\
        use_pca=True,sphere=True,output=False,kwargs_tr={},LAYG=False,k=50,use_tree=True):
        '''
        - param_vals is ndarray with shape [N_params,N_samples]

        - transform param_vals to Sphered_Param_Vals
        - calculate eigenmode construction of predicted signal given param_vals
        eigenmode = weights * eigenvector = w_tr * f_j
        - given a list of parameter vals (ex. [[0.85],[40000.0],[30.0]]) and assuming eigenmodes
        and the best-fit polynomial of their weights have been trained over a training set,
        calculate the weight constants (w_tr) of each eigenmode
        '''
        # Ensure Xpred isn't a row vector
        if Xpred.ndim == 1:
            Xpred = Xpred.reshape(1,-1)

        # Chi Square Multiplier, 95% prob
        self.csm = np.sqrt([3.841,5.991,7.815,9.488,11.070,12.592,14.067,15.507,16.919])

        # Transform to whitened parameter space
        Xpred_shape = Xpred.shape
        if sphere == True:
            Xpred_sph = np.dot(self.invL,(Xpred-self.fid_params).T).T
        else:
            Xpred_sph = Xpred

        if use_Nmodes is None:
            use_Nmodes = self.N_modes

        # Check for LAYG
        if LAYG == True:
            self.sphere(self.grid_tr, fid_params=self.fid_params, invL=self.invL)
            grid_NN = self.nearest(Xpred_sph.ravel(), k=k, use_tree=use_tree)[1]
            self.train(self.data_tr[grid_NN],self.grid_tr[grid_NN],fid_data=self.fid_data,
                            fid_params=self.fid_params,**kwargs_tr)

        # Polynomial Interpolation
        if self.reg_meth == 'poly':
            # Calculate weights
            if Xpred_sph.ndim == 1: Xpred_sph = Xpred_sph.reshape(1,len(Xpred_sph))
            A = self.poly_design_mat(Xpred_sph.T,dim=self.N_params,degree=self.poly_deg)
            weights = np.dot(A,self.xhat)

            # Renormalize weights
            weights *= self.w_norm

            # Compute construction
            if use_pca == True:
                recon = np.dot(weights.T[:use_Nmodes].T,self.eig_vecs[:use_Nmodes])
            else:
                recon = weights.T[0]

            weights_err = self.stand_err.reshape(weights.shape) * self.w_norm
 
        # Gaussian Process Interpolation
        if self.reg_meth == 'gaussian':
            # Iterate over GPs
            weights, MSE = np.zeros((len(Xpred_sph), self.N_modes)), np.zeros((len(Xpred_sph), self.N_modes))
            for i in range(len(self.GP)):
                result = self.GP[i].predict(Xpred_sph, return_cov=(fast==False))
                if fast == True:
                    w = np.array(result)
                    mse = np.zeros(w.shape)
                else:
                    w = np.array(result[0])
                    mse = np.array([np.sqrt(np.array(result[1]).diagonal()) for i in range(len(self.modegroups[i]))]).T
                weights[:,self.modegroups[i]] = w
                MSE[:,self.modegroups[i]] = mse

            if weights.ndim == 1:
                weights = weights.reshape(1,-1)
                MSE = MSE.reshape(1,-1)

            # Renormalize weights
            weights *= self.w_norm
            weights_err = np.sqrt(MSE) * np.sqrt(self.w_norm)

            # Compute reconstruction
            if use_pca == True:
                recon = np.dot(weights.T[:use_Nmodes].T,self.eig_vecs[:use_Nmodes])
            else:
                recon = weights

        # Un-scale the data
        if self.scale_by_std == True:
            recon *= self.Dstd

        if self.scale_by_yerrs == True:
            recon *= self.rescale

        # Un-log and un-center the data
        if self.lognorm == True:
            recon = np.exp(recon) * self.fid_data
        else:
            recon += self.fid_data

        # Calculate Error
        if fast == True:
            recon_err = np.zeros((len(Xpred_sph), self.eig_vecs.shape[1]))
            recon_err_cov = np.zeros((len(Xpred_sph), self.eig_vecs.shape[1], self.eig_vecs.shape[1]))

        else:
            if use_pca == True:
                emode_err = np.array(map(lambda x: (x*self.eig_vecs.T).T, weights_err))
                if self.scale_by_yerrs == True:
                    emode_err *= self.rescale
                if self.scale_by_std == True:
                    emode_err *= self.Dstd
                recon_err = np.sqrt( np.array(map(lambda x: np.sum(x,axis=0),emode_err**2)) )
                recon_err_cov = np.sum([[np.outer(emode_err[i,j], emode_err[i,j]) for j in range(self.N_modes)] for i in range(len(recon))], axis=1)

            else:
                recon_err = weights_err
                recon_err_cov = np.array([np.eye(len(recon.T[i]),len(recon.T[i])) * recon_err.T[i] for i in range(len(recon.T))]).T

            # ReNormalize Error
            if self.lognorm == True:
                recon_err = np.array([recon_err[i]*recon[i] for i in range(len(recon))])
                recon_err_cov = np.array([recon_err_cov[i]*np.outer(recon[i],recon[i]) for i in range(len(recon))])

        # Calibrate recon
        recon *= self.recon_calib

        # Calibrate Error
        recon_err *= self.recon_err_calib
        recon_err_cov *= self.recon_err_calib**2

        # Construct data product and error on data product
        if fast == False:
            names = ['recon','weights','MSE','weights_err','Xpred_sph','recon_err','recon_err_cov']
            self.update(ezcreate(names,locals()))
        else:
            self.recon = recon
            self.recon_err = recon_err
            self.weights = weights
            self.weights_err = weights_err
            self.recon_err_cov = recon_err_cov

        if output == True:
            return recon, recon_err, recon_err_cov, weights, weights_err


