"""
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
"""

import pytest
from aws_cdk.aws_stepfunctions_tasks import GlueStartJobRun

from solution.infrastructure.glue_helper.glue_sfn_update import (
    METRIC_COLLECTION_SQL_QUERY,
    NAMING_SCRIPT_APPENDIX,
    SORTING_SQL_QUERY,
    GlueSfnUpdate,
)
from solution.infrastructure.stack import SolutionStack


@pytest.fixture
def glue_sfn_update(stack: SolutionStack) -> GlueSfnUpdate:
    glue_sfn_update = GlueSfnUpdate(
        stack,
        "test-bucket",
        "arn:aws:s3:::test-bucket",
        "test-job",
        "arn:aws:glue:us-east-1:123456789012:job/test-job",
        "metric_table_name",
        1,
    )
    return glue_sfn_update


def test_autogenerate_etl_script(glue_sfn_update: GlueSfnUpdate) -> None:
    task = glue_sfn_update.autogenerate_etl_script(id="test-1")
    state_json = task.to_state_json()
    resource = state_json["Resource"]
    FIVE_TERABYTES = str(5 * 2**40)
    assert state_json == {
        "End": True,
        "Type": "Task",
        "ResultPath": "$.glue_job_auto_generate_etl_result",
        "Resource": resource,
        "Parameters": {
            "JobName": "test-job",
            "JobUpdate": {
                "GlueVersion": "3.0",
                "Role": "arn:aws:glue:us-east-1:123456789012:job/test-job",
                "ExecutionProperty": {"MaxConcurrentRuns": 1},
                "CodeGenConfigurationNodes": {
                    "node-1": {
                        "S3CsvSource": {
                            "Name": "S3 bucket - Original Inventory",
                            "Paths.$": "States.Array(States.Format('s3://test-bucket/{}/original_inventory/', $.workflow_run))",
                            "QuoteChar": "quote",
                            "Separator": "comma",
                            "Recurse": True,
                            "WithHeader": True,
                            "Escaper": "\\",
                            "OutputSchemas": [
                                {
                                    "Columns": glue_sfn_update.csv_file_columns,
                                }
                            ],
                        }
                    },
                    "node-2": {
                        "ApplyMapping": {
                            "Name": "ConvertSizeToInt",
                            "Inputs": ["node-1"],
                            "Mapping": [
                                {
                                    "ToKey": "ArchiveId",
                                    "FromPath": ["ArchiveId"],
                                    "FromType": "string",
                                    "ToType": "string",
                                },
                                {
                                    "ToKey": "ArchiveDescription",
                                    "FromPath": ["ArchiveDescription"],
                                    "FromType": "string",
                                    "ToType": "string",
                                },
                                {
                                    "ToKey": "CreationDate",
                                    "FromPath": ["CreationDate"],
                                    "FromType": "string",
                                    "ToType": "string",
                                },
                                {
                                    "ToKey": "Size",
                                    "FromPath": ["Size"],
                                    "FromType": "string",
                                    "ToType": "bigint",
                                },
                                {
                                    "ToKey": "SHA256TreeHash",
                                    "FromPath": ["SHA256TreeHash"],
                                    "FromType": "string",
                                    "ToType": "string",
                                },
                            ],
                        }
                    },
                    "node-3": {
                        "Filter": {
                            "Name": "Filter<=5TB",
                            "Inputs": ["node-2"],
                            "LogicalOperator": "AND",
                            "Filters": [
                                {
                                    "Operation": "LTE",
                                    "Negated": False,
                                    "Values": [
                                        {"Type": "COLUMNEXTRACTED", "Value": ["Size"]},
                                        {"Type": "CONSTANT", "Value": [FIVE_TERABYTES]},
                                    ],
                                }
                            ],
                        }
                    },
                    "node-4": {
                        "Filter": {
                            "Name": "Filter>5TB",
                            "Inputs": ["node-2"],
                            "LogicalOperator": "AND",
                            "Filters": [
                                {
                                    "Operation": "GT",
                                    "Negated": False,
                                    "Values": [
                                        {"Type": "COLUMNEXTRACTED", "Value": ["Size"]},
                                        {"Type": "CONSTANT", "Value": [FIVE_TERABYTES]},
                                    ],
                                }
                            ],
                        }
                    },
                    "node-5": {
                        "CustomCode": {
                            "Name": "ValidateInput<=5TB",
                            "Inputs": ["node-3"],
                            "ClassName": "validate_source_table",
                            "Code": glue_sfn_update.validate_source_input_custom_code,
                        }
                    },
                    "node-6": {
                        "CustomCode": {
                            "Name": "ValidateInput>5TB",
                            "Inputs": ["node-4"],
                            "ClassName": "validate_source_table",
                            "Code": glue_sfn_update.validate_source_input_custom_code,
                        }
                    },
                    "node-7": {
                        "SelectFromCollection": {
                            "Name": "SelectFromCollection<=5TB",
                            "Inputs": ["node-5"],
                            "Index": 0,
                        }
                    },
                    "node-8": {
                        "SelectFromCollection": {
                            "Name": "SelectFromCollection>5TB",
                            "Inputs": ["node-6"],
                            "Index": 0,
                        }
                    },
                    "node-9": {
                        "CustomCode": {
                            "Name": "ArchiveNaming",
                            "Inputs": ["node-7"],
                            "ClassName": "ArchiveNaming",
                            "Code": glue_sfn_update.custom_code,
                        }
                    },
                    "node-10": {
                        "SparkSQL": {
                            "Name": "SQL Metric",
                            "Inputs": ["node-7"],
                            "SqlQuery": METRIC_COLLECTION_SQL_QUERY,
                            "SqlAliases": [{"From": "node-7", "Alias": "myDataSource"}],
                            "OutputSchemas": [
                                {
                                    "Columns": [
                                        {
                                            "Name": "TotalArchivesNumber",
                                            "Type": "bigint",
                                        },
                                        {"Name": "TotalArchivesSize", "Type": "bigint"},
                                    ]
                                }
                            ],
                        }
                    },
                    "node-11": {
                        "SparkSQL": {
                            "Name": "SQL Skipped Metric",
                            "Inputs": ["node-8"],
                            "SqlQuery": METRIC_COLLECTION_SQL_QUERY,
                            "SqlAliases": [{"From": "node-8", "Alias": "myDataSource"}],
                            "OutputSchemas": [
                                {
                                    "Columns": [
                                        {
                                            "Name": "TotalArchivesNumber",
                                            "Type": "bigint",
                                        },
                                        {"Name": "TotalArchivesSize", "Type": "bigint"},
                                    ]
                                }
                            ],
                        }
                    },
                    "node-12": {
                        "S3DirectTarget": {
                            "Name": "S3 bucket - Not Migrated",
                            "Inputs": ["node-8"],
                            "Compression": "none",
                            "Format": "csv",
                            "SchemaChangePolicy": {"EnableUpdateCatalog": False},
                            "Path.$": "States.Format('s3://test-bucket/{}/not_migrated/', $.workflow_run)",
                        }
                    },
                    "node-13": {
                        "SelectFromCollection": {
                            "Name": "SelectFromCollection",
                            "Inputs": ["node-9"],
                            "Index": 0,
                        }
                    },
                    "node-14": {
                        "CustomCode": {
                            "Name": "MetricCollection",
                            "Inputs": ["node-10", "node-11"],
                            "ClassName": "MetricCollection",
                            "Code": glue_sfn_update.metric_collection_code,
                        }
                    },
                    "node-15": {
                        "S3CsvSource": {
                            "Name": "S3 bucket - Naming Overrides",
                            "Paths.$": "States.Array(States.Format('s3://test-bucket/{}/naming_overrides/', $.workflow_run))",
                            "QuoteChar": "quote",
                            "Separator": "comma",
                            "Recurse": True,
                            "WithHeader": True,
                            "Escaper": "",
                            "OutputSchemas": [
                                {
                                    "Columns": glue_sfn_update.archive_naming_override_columns,
                                }
                            ],
                        },
                    },
                    "node-16": {
                        "SparkSQL": {
                            "Name": "SQL sorting",
                            "Inputs": ["node-15", "node-13"],
                            "SqlQuery": SORTING_SQL_QUERY,
                            "SqlAliases": [
                                {"From": "node-15", "Alias": "namingOverrides"},
                                {"From": "node-13", "Alias": "myDataSource"},
                            ],
                            "OutputSchemas": [
                                {"Columns": glue_sfn_update.csv_file_columns_output}
                            ],
                        }
                    },
                    "node-17": {
                        "CustomCode": {
                            "Name": "Validation",
                            "Inputs": ["node-7", "node-16"],
                            "ClassName": "Validation",
                            "Code": "\nnode_inputs = list(dfc.values())\nassert node_inputs[0].toDF().count() == node_inputs[1].toDF().count()\n",
                        }
                    },
                    "node-18": {
                        "S3DirectTarget": {
                            "Name": "S3 bucket - Sorted Inventory",
                            "Inputs": ["node-16"],
                            "PartitionKeys.$": "States.Array(States.Array('PartitionId'))",
                            "Compression": "none",
                            "Format": "csv",
                            "SchemaChangePolicy": {"EnableUpdateCatalog": False},
                            "Path.$": "States.Format('s3://test-bucket/{}/sorted_inventory/', $.workflow_run)",
                        }
                    },
                },
                "Command": {
                    "Name": "glueetl",
                    "ScriptLocation.$": "States.Format('s3://test-bucket/{}/scripts/inventory_sort_script.py', $.workflow_run)",
                    "PythonVersion": "3",
                },
            },
        },
    }


def test_start_job(glue_sfn_update: GlueSfnUpdate) -> None:
    task = glue_sfn_update.start_job(id="test-2")
    state_json = task.to_state_json()
    assert isinstance(task, GlueStartJobRun)
    assert state_json["Parameters"]["JobName"] == "test-job"
    assert state_json["Parameters"]["Arguments"]["--enable-job-insights"] == "true"
    assert (
        state_json["Parameters"]["Arguments"]["--enable-continuous-cloudwatch-log"]
        == "true"
    )
    assert state_json["Parameters"]["Arguments"]["--job-language"] == "python"
