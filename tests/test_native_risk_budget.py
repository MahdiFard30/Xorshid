"""Execute the EA's exact pure budget function, without broker access."""
from pathlib import Path
import random
import shutil
import subprocess

import pytest


@pytest.fixture(scope='module')
def binary(tmp_path_factory):
    compiler=shutil.which('g++')
    if not compiler: pytest.skip('C++ compiler required')
    folder=tmp_path_factory.mktemp('native-risk')
    header=Path(__file__).resolve().parents[1]/'mt5/RestartPolicy.mqh'
    source=folder/'budget.cpp'
    source.write_text('#include <iostream>\n#include <iomanip>\n#include <cstdlib>\n'
        '#include "'+str(header)+'"\n'
        'int main(int n,char** v){std::cout<<std::setprecision(17)<<AllocationBudget('
        'atof(v[1]),atof(v[2]),atof(v[3]),atof(v[4]),atof(v[5]),atof(v[6]));}')
    output=folder/'budget'
    subprocess.run([compiler,str(source),'-o',str(output)],capture_output=True,check=True)
    return output


def budget(binary,equity=100000,fraction=.005,cap=.005,used=0,total=0,usd=0):
    result=subprocess.run([str(binary),*map(str,(equity,fraction,cap,used,total,usd))],capture_output=True,text=True,check=True)
    return float(result.stdout)


@pytest.mark.parametrize('change',[
    {'fraction':.005001},{'fraction':0},{'fraction':-1},{'fraction':float('nan')},
    {'cap':.005001},{'cap':.0001},{'used':-1},{'total':float('inf')},{'usd':-1},{'equity':0},
])
def test_invalid_requests_never_produce_a_budget(binary,change):
    assert budget(binary,**change)<0


def test_native_hard_caps_apply_even_if_python_sizing_is_wrong(binary):
    assert budget(binary)==500
    assert budget(binary,used=495)==5
    assert budget(binary,total=498)==2
    assert budget(binary,usd=499)==1
    assert budget(binary,usd=500)==0


def test_random_valid_budgets_respect_every_native_ceiling(binary):
    rng=random.Random(63)
    for _ in range(100):
        fraction=rng.uniform(.00001,.005);cap=rng.uniform(fraction,.005)
        used=rng.uniform(0,500);total=rng.uniform(used,500);usd=rng.uniform(0,500)
        value=budget(binary,fraction=fraction,cap=cap,used=used,total=total,usd=usd)
        assert 0<=value<=100000*fraction+1e-9
        assert value<=max(0,100000*cap-used)+1e-9
        assert value<=max(0,500-total)+1e-9
        assert value<=max(0,500-usd)+1e-9


def test_python_and_native_caps_agree_at_the_requested_half_percent(binary):
    from ultimate_khorshid.tools import portfolio_policy as policy
    assert policy.ENTRY_CAP==policy.SYMBOL_CAP==policy.PORTFOLIO_CAP==policy.USD_SIDE_CAP==.005
    assert budget(binary,fraction=policy.ENTRY_CAP,cap=policy.SYMBOL_CAP)==500
    assert budget(binary,total=500)==0
    assert budget(binary,used=400,total=450,usd=425)==50
